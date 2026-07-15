"""
AI голосовой бот: Mango SIP + Yandex SpeechKit + Claude.

Схема:
  autocall.py → Mango Callback API → Mango звонит на наш SIP (doctor@vpbx...)
  → pyVoIP отвечает → пациент говорит → Yandex STT → Claude → Yandex TTS → пациент слышит
"""
import os
import io
import asyncio
import logging
import threading
import time
import audioop
import wave

import httpx
from anthropic import Anthropic

log = logging.getLogger("voice_bot")

# ── Конфигурация ─────────────────────────────────────────────────────────────

SIP_USER   = os.getenv("SIP_USER",   "doctor")
SIP_PASS   = os.getenv("SIP_PASS",   "")
SIP_DOMAIN = os.getenv("SIP_DOMAIN", "vpbx400375166.mangosip.ru")
SIP_PORT   = int(os.getenv("SIP_PORT", "5060"))

YANDEX_KEY       = os.getenv("YANDEX_API_KEY", "")
YANDEX_FOLDER_ID = os.getenv("YANDEX_FOLDER_ID", "")

_claude = Anthropic(
    api_key=os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_KEY", "")
)

# RTP / аудио
SAMPLE_RATE       = 8000   # G.711 ulaw
FRAME_SIZE        = 160    # 20 мс
SILENCE_RMS       = 400    # порог тишины
SILENCE_FRAMES    = 25     # ~500 мс тишины → конец фразы

# ── Yandex SpeechKit ─────────────────────────────────────────────────────────

async def _stt(pcm: bytes) -> str:
    """16-bit PCM 8кГц моно → текст."""
    if not YANDEX_KEY or len(pcm) < 1600:
        return ""
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(
                "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize",
                params={"lang": "ru-RU", "format": "lpcm",
                        "sampleRateHertz": SAMPLE_RATE,
                        "folderId": YANDEX_FOLDER_ID},
                content=pcm,
                headers={"Authorization": f"Api-Key {YANDEX_KEY}"},
            )
        if r.status_code == 200:
            return r.json().get("result", "")
        log.warning(f"STT {r.status_code}: {r.text[:120]}")
    except Exception as e:
        log.error(f"STT error: {e}")
    return ""


async def _tts(text: str) -> bytes:
    """Текст → 16-bit PCM 8кГц."""
    if not YANDEX_KEY or not text:
        return b""
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(
                "https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize",
                data={"text": text[:200], "lang": "ru-RU", "voice": "alena",
                      "speed": "1.1", "format": "lpcm",
                      "sampleRateHertz": str(SAMPLE_RATE),
                      "folderId": YANDEX_FOLDER_ID},
                headers={"Authorization": f"Api-Key {YANDEX_KEY}"},
            )
        if r.status_code == 200:
            return r.content
        log.warning(f"TTS {r.status_code}: {r.text[:120]}")
    except Exception as e:
        log.error(f"TTS error: {e}")
    return b""


# ── Claude ───────────────────────────────────────────────────────────────────

def _ai_reply(history: list, system: str) -> str:
    try:
        resp = _claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=120,
            system=system,
            messages=history,
        )
        return resp.content[0].text.strip()
    except Exception as e:
        log.error(f"Claude: {e}")
        return "Один момент, пожалуйста."


# ── Сессия звонка ─────────────────────────────────────────────────────────────

_GOALS = {
    "wellbeing": "узнать как пациент себя чувствует после вчерашнего приёма",
    "hygiene":   "напомнить о профессиональной гигиене зубов каждые 3 месяца",
    "checkup":   "пригласить на профилактический осмотр (прошло полгода)",
    "confirm":   "подтвердить запись на приём",
    "implant":   "узнать как проходит заживление после имплантации",
}

_GREETINGS = {
    "wellbeing": "Добрый день, {name}! Это клиника Аура. Как вы себя чувствуете после вчерашнего приёма?",
    "hygiene":   "Добрый день, {name}! Это клиника Аура. Напоминаем о профессиональной чистке зубов — прошло три месяца. Хотите записаться?",
    "checkup":   "Добрый день, {name}! Это клиника Аура. Прошло полгода с вашего последнего визита — пора на осмотр. Вам удобно?",
    "confirm":   "Добрый день, {name}! Это клиника Аура. Хотим подтвердить вашу запись на приём.",
    "implant":   "Добрый день, {name}! Это клиника Аура. Как проходит заживление после имплантации? Никаких жалоб нет?",
}


class CallSession:
    def __init__(self, call, patient_name: str, call_type: str):
        self.call         = call
        self.patient_name = patient_name
        self.call_type    = call_type
        self.history      = []
        self.buf          = b""
        self.silence_cnt  = 0
        self.has_voice    = False
        self.loop         = asyncio.new_event_loop()

        fname = patient_name.split()[0] if patient_name else "пациент"
        self.system = (
            f"Ты — голосовой ассистент стоматологической клиники Аура. "
            f"Звонишь пациенту {fname}. Цель: {_GOALS.get(call_type, 'помочь пациенту')}. "
            f"Отвечай ОЧЕНЬ кратко — 1-2 коротких предложения. "
            f"Говори тепло и профессионально. Если хочет записаться — "
            f"скажи что передашь информацию администратору и он перезвонит."
        )
        self._greeting = _GREETINGS.get(
            call_type,
            f"Добрый день, {fname}! Это клиника Аура."
        ).format(name=fname)

    # ── аудио pipeline ──────────────────────────────────────────

    def on_frame(self, ulaw_frame: bytes):
        """Вызывается из потока RTP на каждый 20-мс фрейм."""
        pcm = audioop.ulaw2lin(ulaw_frame, 2)
        rms = audioop.rms(pcm, 2)

        if rms > SILENCE_RMS:
            self.buf        += pcm
            self.silence_cnt = 0
            self.has_voice   = True
        elif self.has_voice:
            self.buf        += pcm
            self.silence_cnt += 1
            if self.silence_cnt >= SILENCE_FRAMES:
                chunk          = self.buf
                self.buf       = b""
                self.has_voice = False
                self.silence_cnt = 0
                asyncio.run_coroutine_threadsafe(
                    self._process(chunk), self.loop
                )

    async def _process(self, pcm: bytes):
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
            self._send(audio)

    def _send(self, pcm: bytes):
        """Отправляем PCM → G.711 → RTP."""
        ulaw = audioop.lin2ulaw(pcm, 2)
        for i in range(0, len(ulaw), FRAME_SIZE):
            chunk = ulaw[i:i + FRAME_SIZE]
            if len(chunk) < FRAME_SIZE:
                chunk += b"\x7f" * (FRAME_SIZE - len(chunk))
            try:
                self.call.write_audio(chunk)
            except Exception:
                break
            time.sleep(0.019)

    # ── жизненный цикл ──────────────────────────────────────────

    def start(self):
        threading.Thread(target=self._run_loop, daemon=True).start()

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._greet())
        self.loop.run_forever()

    async def _greet(self):
        self.history.append({"role": "assistant", "content": self._greeting})
        audio = await _tts(self._greeting)
        if audio:
            self._send(audio)

    def stop(self):
        self.loop.call_soon_threadsafe(self.loop.stop)


# ── Глобальное состояние ─────────────────────────────────────────────────────

_sessions: dict[str, CallSession] = {}
_pending:  dict[str, dict]        = {}   # commandId → {patient_name, call_type}
_phone     = None


def register_call(command_id: str, patient_name: str, call_type: str):
    """
    Вызывается из autocall.py сразу после отправки запроса в Mango.
    Сохраняем метаданные чтобы связать с входящим SIP звонком.
    """
    _pending[command_id] = {"patient_name": patient_name, "call_type": call_type}
    log.debug(f"pending call registered: {command_id}")


def _on_call(call):
    """Обработчик входящего SIP вызова от Mango."""
    call.answer()

    # Mango передаёт commandId в SIP заголовке X-Mango-Command-Id (или похожем)
    # Если не нашли — берём последний pending
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
    call_id = id(call)
    _sessions[call_id] = session
    session.start()

    try:
        while True:
            frame = call.read_audio(FRAME_SIZE)
            if not frame:
                break
            session.on_frame(frame)
    finally:
        session.stop()
        _sessions.pop(call_id, None)
        log.info(f"Звонок завершён: {patient_name}")


# ── Запуск ────────────────────────────────────────────────────────────────────

def start(bot=None):
    global _phone

    if not SIP_PASS:
        log.warning("SIP_PASS не задан — голосовой бот отключён")
        return

    try:
        from pyVoIP.VoIP import VoIPPhone
    except ImportError:
        log.error("Установи pyVoIP: pip install pyVoIP")
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
        log.info(f"SIP online: {SIP_USER}@{SIP_DOMAIN}")
    except Exception as e:
        log.error(f"SIP start failed: {e}")
