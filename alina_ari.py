#!/usr/bin/env python3
"""
Алина — AI телефонный агент на Asterisk ARI.
Запуск: python3 alina_ari.py
"""

import asyncio
import aiohttp
import os
import json
import shutil
import tempfile
from pathlib import Path
from openai import AsyncOpenAI
import anthropic

# Asterisk ARI
ASTERISK_HOST = "localhost"
ASTERISK_PORT = 8088
ARI_APP = "alina"
ARI_USER = os.getenv("ARI_USER", "alina")
ARI_PASS = os.getenv("ARI_PASS", "alina_secret_2024")
ASTERISK_URL = f"http://{ASTERISK_HOST}:{ASTERISK_PORT}"

SOUNDS_DIR = Path("/opt/alina/sounds")
SOUNDS_DIR.mkdir(parents=True, exist_ok=True)

openai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
claude_client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Telegram notification
TG_TOKEN = os.getenv("BOT_TOKEN", "")
TG_ADMIN = os.getenv("ADMIN_CHAT_ID", "")

SYSTEM_PROMPT = """Ты Алина — нежный и очень профессиональный администратор стоматологической клиники «Аура Дент».

Твои задачи:
- Записать пациента на приём (спросить имя, желаемое время, врача или процедуру)
- Ответить на вопросы о клинике, услугах, ценах
- Напомнить о предстоящем визите
- При записи — подтвердить детали и попрощаться

Правила:
- Отвечай кратко: 1-2 предложения максимум
- Говори тепло, с заботой, по-русски
- Если записываешь пациента — в конце скажи точные дату/время записи
- Когда прощаешься — обязательно скажи "До свидания" или "Всего доброго"

Клиника работает: Пн-Сб 9:00-20:00, Вс 10:00-17:00.
Адрес: уточни у пациента удобный способ получить адрес."""


async def tts(text: str) -> str:
    """OpenAI TTS → WAV. Возвращает путь к файлу."""
    cache_name = "".join(c for c in text[:40] if c.isalnum() or c in " _")
    wav_path = SOUNDS_DIR / f"{cache_name}.wav"
    if wav_path.exists():
        return str(wav_path)

    response = await openai_client.audio.speech.create(
        model="tts-1",
        voice="nova",
        input=text,
        response_format="wav",
        speed=0.92,
    )
    wav_path.write_bytes(response.content)
    return str(wav_path)


async def stt(wav_path: str) -> str:
    """Whisper STT → текст."""
    with open(wav_path, "rb") as f:
        transcript = await openai_client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            language="ru",
        )
    return transcript.text.strip()


async def notify_telegram(text: str):
    if not TG_TOKEN or not TG_ADMIN:
        return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    async with aiohttp.ClientSession() as s:
        await s.post(url, json={"chat_id": TG_ADMIN, "text": text, "parse_mode": "HTML"})


class AlinaCall:
    def __init__(self, channel_id: str, caller: str, session: aiohttp.ClientSession):
        self.channel_id = channel_id
        self.caller = caller
        self.session = session
        self.history: list[dict] = []
        self.auth = aiohttp.BasicAuth(ARI_USER, ARI_PASS)
        self.base = f"{ASTERISK_URL}/ari"

    async def _api(self, method: str, path: str, **kw):
        url = f"{self.base}{path}"
        async with self.session.request(method, url, auth=self.auth, **kw) as r:
            try:
                return await r.json()
            except Exception:
                return {}

    async def answer(self):
        await self._api("POST", f"/channels/{self.channel_id}/answer")

    async def hangup(self):
        await self._api("DELETE", f"/channels/{self.channel_id}")

    async def play_text(self, text: str):
        """TTS → копируем в Asterisk sounds → играем."""
        src = await tts(text)
        dst = f"/var/lib/asterisk/sounds/alina_play_{self.channel_id}.wav"
        shutil.copy(src, dst)

        pb = await self._api(
            "POST",
            f"/channels/{self.channel_id}/play",
            json={"media": f"sound:alina_play_{self.channel_id}"},
        )
        pb_id = pb.get("id", "")

        # Ждём пропорционально длине текста (примерно 80 слов/мин)
        words = len(text.split())
        wait = max(2.0, words * 0.75)
        await asyncio.sleep(wait)
        return pb_id

    async def record_caller(self, max_sec: int = 10) -> str | None:
        """Записываем речь пациента. Возвращает путь к WAV или None."""
        rec_name = f"alina_rec_{self.channel_id}"
        await self._api(
            "POST",
            f"/channels/{self.channel_id}/record",
            json={
                "name": rec_name,
                "format": "wav",
                "maxDurationSeconds": max_sec,
                "maxSilenceSeconds": 2,
                "beep": False,
                "ifExists": "overwrite",
            },
        )
        await asyncio.sleep(max_sec + 1)
        path = f"/var/spool/asterisk/recording/{rec_name}.wav"
        return path if Path(path).exists() else None

    async def ai_reply(self, user_text: str) -> tuple[str, bool]:
        self.history.append({"role": "user", "content": user_text})
        resp = await claude_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=200,
            system=SYSTEM_PROMPT,
            messages=self.history,
        )
        reply = resp.content[0].text.strip()
        self.history.append({"role": "assistant", "content": reply})
        end = any(w in reply.lower() for w in ["до свидания", "всего доброго", "спасибо за звонок", "до встречи"])
        return reply, end

    async def run(self):
        await self.answer()
        await asyncio.sleep(0.5)

        await notify_telegram(f"📞 Входящий звонок от <b>{self.caller}</b>\nАлина отвечает...")

        greeting = "Здравствуйте! Стоматология Аура Дент, меня зовут Алина. Чем могу помочь?"
        await self.play_text(greeting)
        self.history.append({"role": "assistant", "content": greeting})

        transcript_lines = [f"📞 Звонок {self.caller}"]

        for turn in range(12):
            rec_path = await self.record_caller(max_sec=10)

            if not rec_path:
                await self.play_text("Не слышу вас. Пожалуйста, перезвоните. До свидания!")
                break

            user_text = await stt(rec_path)
            print(f"[{self.channel_id}] 👤 {user_text}")
            transcript_lines.append(f"👤 {user_text}")

            if not user_text:
                await self.play_text("Извините, не расслышала. Можете повторить?")
                continue

            reply, end_call = await self.ai_reply(user_text)
            print(f"[{self.channel_id}] 🤖 {reply}")
            transcript_lines.append(f"🤖 {reply}")

            await self.play_text(reply)

            if end_call:
                break

        await asyncio.sleep(0.5)
        await self.hangup()

        summary = "\n".join(transcript_lines)
        await notify_telegram(f"✅ Звонок завершён\n\n{summary}")
        print(f"[{self.channel_id}] Звонок завершён")


# ── Обработчик событий ARI ────────────────────────────────────────────────────

active_calls: dict[str, AlinaCall] = {}


async def handle_event(event: dict, session: aiohttp.ClientSession):
    etype = event.get("type")

    if etype == "StasisStart":
        ch = event.get("channel", {})
        cid = ch.get("id")
        caller = ch.get("caller", {}).get("number", "unknown")
        print(f"[ARI] StasisStart: {caller} → {cid}")
        call = AlinaCall(cid, caller, session)
        active_calls[cid] = call
        asyncio.create_task(call.run())

    elif etype == "StasisEnd":
        cid = event.get("channel", {}).get("id")
        active_calls.pop(cid, None)
        print(f"[ARI] StasisEnd: {cid}")

    elif etype == "ChannelHangupRequest":
        cid = event.get("channel", {}).get("id")
        print(f"[ARI] HangupRequest: {cid}")


async def main():
    ws_url = (
        f"ws://{ASTERISK_HOST}:{ASTERISK_PORT}/ari/events"
        f"?api_key={ARI_USER}:{ARI_PASS}&app={ARI_APP}&subscribeAll=true"
    )
    print(f"Алина ARI агент стартует... WS: {ws_url}")

    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.ws_connect(ws_url) as ws:
                    print("✅ Подключён к Asterisk ARI — жду звонков")
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            event = json.loads(msg.data)
                            if event.get("type") not in ("ContactStatusChange",):
                                await handle_event(event, session)
                        elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                            break
            except Exception as e:
                print(f"ARI ошибка: {e} — переподключение через 5 сек")
                await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
