"""
AI голосовой бот: Mango SIP + OpenAI Whisper (STT) + OpenAI TTS + Claude.

Схема:
  autocall.py → Mango Callback API → Mango звонит на SIP doctor@vpbx400375166.mangosip.ru
  → pyVoIP отвечает → пациент говорит → Whisper STT → Claude Haiku → OpenAI TTS → пациент слышит

Переменные Railway:
  SIP_USER, SIP_PASS, SIP_DOMAIN, OPENAI_API_KEY
"""
import os
import io
import wave
import asyncio
import audioop
import logging
import threading
import time

import httpx
from anthropic import Anthropic

log = logging.getLogger("voice_bot")

# ── Конфиг ───────────────────────────────────────────────────────────────────

SIP_USER   = os.getenv("SIP_USER",   "doctor")
SIP_PASS   = os.getenv("SIP_PASS",   "")
SIP_DOMAIN = os.getenv("SIP_DOMAIN", "vpbx400375166.mangosip.ru")
SIP_PORT   = int(os.getenv("SIP_PORT", "5060"))

OPENAI_KEY    = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_KEY", "")

_claude = Anthropic(api_key=ANTHROPIC_KEY) if ANTHROPIC_KEY else None

# RTP
SAMPLE_RATE    = 8000
FRAME_SIZE     = 160    # 20 мс
SILENCE_RMS    = 400
SILENCE_FRAMES = 25     # ~500 мс тишины = конец фразы

# ── TTS: OpenAI → PCM 8kHz ───────────────────────────────────────────────────

async def _tts(text: str) -> bytes:
    """Текст → 16-bit PCM 8кГц через OpenAI TTS."""
    if not OPENAI_KEY or not text:
        return b""
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                "https://api.openai.com/v1/audio/speech",
                headers={"Authorization": f"Bearer {OPENAI_KEY}"},
                json={
                    "model": "tts-1",
                    "input": text[:500],
                    "voice": "nova",          # женский голос, звучит мягко
                    "response_format": "pcm", # 24kHz 16-bit signed LE
                },
            )
        if r.status_code == 200:
            pcm_24k = r.content
            # Ресэмплируем 24кГц → 8кГц
            pcm_8k, _ = audioop.ratecv(pcm_24k, 2, 1, 24000, 8000, None)
            return pcm_8k
        log.warning(f"TTS {r.status_code}: {r.text[:120]}")
    except Exception as e:
        log.error(f"TTS error: {e}")
    return b""


# ── STT: OpenAI Whisper ───────────────────────────────────────────────────────

async def _stt(pcm: bytes) -> str:
    """16-bit PCM 8кГц → текст через OpenAI Whisper."""
    if not OPENAI_KEY or len(pcm) < 3200:   # < 200ms → пропускаем
        return ""
    # Оборачиваем в WAV
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm)
    buf.seek(0)
    buf.name = "audio.wav"

    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {OPENAI_KEY}"},
                files={"file": ("audio.wav", buf, "audio/wav")},
                data={"model": "whisper-1", "language": "ru"},
            )
        if r.status_code == 200:
            return r.json().get("text", "").strip()
        log.warning(f"STT {r.status_code}: {r.text[:120]}")
    except Exception as e:
        log.error(f"STT error: {e}")
    return ""


# ── Claude ────────────────────────────────────────────────────────────────────

def _ai_reply(history: list, system: str) -> str:
    if not _claude:
        return "Один момент, пожалуйста."
    try:
        resp = _claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            system=system,
            messages=history,
        )
        return resp.content[0].text.strip()
    except Exception as e:
        log.error(f"Claude: {e}")
        return "Один момент, пожалуйста."


# ── Скрипты ───────────────────────────────────────────────────────────────────

_GOALS = {
    "wellbeing": "узнать как пациент себя чувствует после вчерашнего приёма",
    "hygiene":   "напомнить о профессиональной гигиене зубов каждые 3 месяца",
    "checkup":   "пригласить на профилактический осмотр (прошло полгода)",
    "confirm":   "подтвердить запись на приём",
    "implant":   "узнать как проходит заживление после имплантации",
}

_GREET = {
    "wellbeing": "Добрый день, {n}! Это клиника Аура. Как вы себя чувствуете после вчерашнего приёма?",
    "hygiene":   "Добрый день, {n}! Это клиника Аура. Напоминаем о профессиональной чистке зубов — прошло три месяца. Хотите записаться?",
    "checkup":   "Добрый день, {n}! Это клиника Аура. Прошло полгода с вашего визита — пора на осмотр. Удобно?",
    "confirm":   "Добрый день, {n}! Это клиника Аура. Хотим подтвердить вашу запись на приём.",
    "implant":   "Добрый день, {n}! Это клиника Аура. Как проходит заживление? Никаких жалоб нет?",
}


# ── Сессия звонка ─────────────────────────────────────────────────────────────

class CallSession:
    def __init__(self, call, patient_name: str, call_type: str):
        self.call      = call
        self.name      = patient_name
        self.ctype     = call_type
        self.history   = []
        self.buf       = b""
        self.sil_cnt   = 0
        self.voiced    = False
        self.loop      = asyncio.new_event_loop()

        fname = patient_name.split()[0] if patient_name else "пациент"
        self.system = (
            f"Ты — голосовой ассистент клиники Аура. Звонишь пациенту {fname}. "
            f"Цель: {_GOALS.get(call_type, 'помочь пациенту')}. "
            f"Отвечай очень кратко — 1-2 предложения. Тепло, профессионально. "
            f"Если хочет записаться — скажи что передашь администратору."
        )
        self._greeting = _GREET.get(call_type, f"Добрый день! Это клиника Аура.").format(n=fname)

    # ── аудио pipeline ──────────────────────────────────────────────────────

    def on_frame(self, ulaw: bytes):
        pcm = audioop.ulaw2lin(ulaw, 2)
        rms = audioop.rms(pcm, 2)

        if rms > SILENCE_RMS:
            self.buf    += pcm
            self.sil_cnt = 0
            self.voiced  = True
        elif self.voiced:
            self.buf    += pcm
            self.sil_cnt += 1
            if self.sil_cnt >= SILENCE_FRAMES:
                chunk       = self.buf
                self.buf    = b""
                self.voiced = False
                self.sil_cnt = 0
                asyncio.run_coroutine_threadsafe(self._handle(chunk), self.loop)

    async def _handle(self, pcm: bytes):
        text = await _stt(pcm)
        if not text:
            return
        log.info(f"[пациент] {text}")
        self.history.append({"role": "user", "content": text})

        reply = _ai_reply(self.history, self.system)
        log.info(f"[бот] {reply}")
        self.history.append({"role": "assistant", "content": reply})

        audio = await _tts(reply)
        if audio:
            self._play(audio)

    def _play(self, pcm: bytes):
        """PCM 8kHz → G.711 ulaw → RTP."""
        ulaw = audioop.lin2ulaw(pcm, 2)
        for i in range(0, len(ulaw), FRAME_SIZE):
            chunk = ulaw[i:i + FRAME_SIZE].ljust(FRAME_SIZE, b"\x7f")
            try:
                self.call.write_audio(chunk)
            except Exception:
                return
            time.sleep(0.019)

    # ── жизненный цикл ─────────────────────────────────────────────────────

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._greet())
        self.loop.run_forever()

    async def _greet(self):
        self.history.append({"role": "assistant", "content": self._greeting})
        audio = await _tts(self._greeting)
        if audio:
            self._play(audio)
        else:
            log.warning("TTS недоступен — OPENAI_API_KEY не задан?")

    def stop(self):
        self.loop.call_soon_threadsafe(self.loop.stop)


# ── Глобальное состояние ─────────────────────────────────────────────────────

_sessions: dict[int, CallSession] = {}
_pending:  dict[str, dict]        = {}
_phone = None


def register_call(command_id: str, patient_name: str, call_type: str):
    _pending[command_id] = {"patient_name": patient_name, "call_type": call_type}
    log.debug(f"pending: {command_id} → {patient_name} [{call_type}]")


def _on_call(call):
    call.answer()

    meta = {}
    try:
        hdrs = call.request.headers
        cid  = hdrs.get("X-Mango-Command-Id") or hdrs.get("X-Command-Id", "")
        meta = _pending.pop(cid, {})
    except Exception:
        pass
    if not meta and _pending:
        _, meta = _pending.popitem()

    patient_name = meta.get("patient_name", "")
    call_type    = meta.get("call_type", "wellbeing")
    log.info(f"Звонок: {patient_name} [{call_type}]")

    session = CallSession(call, patient_name, call_type)
    cid = id(call)
    _sessions[cid] = session
    session.start()

    try:
        while True:
            frame = call.read_audio(FRAME_SIZE)
            if not frame:
                break
            session.on_frame(frame)
    finally:
        session.stop()
        _sessions.pop(cid, None)
        log.info(f"Завершён: {patient_name}")


# ── Запуск ────────────────────────────────────────────────────────────────────

def start(bot=None):
    global _phone

    if not SIP_PASS:
        log.warning("SIP_PASS не задан — голосовой бот отключён")
        return
    if not OPENAI_KEY:
        log.warning("OPENAI_API_KEY не задан — TTS/STT не работает")

    try:
        from pyVoIP.VoIP import VoIPPhone
    except ImportError:
        log.error("pip install pyVoIP")
        return

    try:
        _phone = VoIPPhone(
            server       = SIP_DOMAIN,
            port         = SIP_PORT,
            username     = SIP_USER,
            password     = SIP_PASS,
            callCallback = _on_call,
            myIP         = "0.0.0.0",
            sipPort      = 5080,
            rtpPortLow   = 10000,
            rtpPortHigh  = 10200,
        )
        _phone.start()
        log.info(f"✅ SIP online: {SIP_USER}@{SIP_DOMAIN}")
    except Exception as e:
        log.error(f"SIP start failed: {e}")
