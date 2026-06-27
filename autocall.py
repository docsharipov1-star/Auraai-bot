"""
Модуль автодозвона — бот сам звонит пациентам.
Телефония: Zadarma (zadarma.com) — ~1.5 руб/мин, бесплатная регистрация.

Как подключить:
1. Зарегистрироваться на zadarma.com
2. Пополнить баланс (минимум 100 руб)
3. Получить API key + secret в личном кабинете
4. Арендовать номер (~60 руб/мес)
5. Добавить ZADARMA_KEY и ZADARMA_SECRET в Railway
"""

import os
import io
import hmac
import time
import hashlib
import asyncio
import logging
import tempfile
import base64
from datetime import datetime, date, timedelta
from typing import Optional

import httpx
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import Response

log = logging.getLogger("autocall")

ZADARMA_KEY    = os.getenv("ZADARMA_KEY", "")
ZADARMA_SECRET = os.getenv("ZADARMA_SECRET", "")
ZADARMA_NUMBER = os.getenv("ZADARMA_NUMBER", "")   # Ваш номер в Zadarma (от кого звонит)
BASE_URL       = os.getenv("BASE_URL", "https://auraai-bot-production.up.railway.app")
ADMIN_TG_ID    = os.getenv("ADMIN_ID", "6766016614")
BOT_TOKEN      = os.getenv("BOT_TOKEN", "")

# Активные звонки: call_id → состояние разговора
_active_calls: dict[str, dict] = {}


# ─── Zadarma API ──────────────────────────────────────────────────────────────

def _zadarma_sign(method: str, params: dict) -> str:
    """Подпись для Zadarma API."""
    param_str = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    data = method + param_str + hashlib.md5(param_str.encode()).hexdigest()
    return base64.b64encode(
        hmac.new(ZADARMA_SECRET.encode(), data.encode(), hashlib.sha1).digest()
    ).decode()


async def zadarma_request(method: str, params: dict = None, http_method="GET") -> dict:
    """Запрос к Zadarma API."""
    if params is None:
        params = {}

    sign = _zadarma_sign(method, params)
    headers = {"Authorization": f"{ZADARMA_KEY}:{sign}"}
    url = f"https://api.zadarma.com{method}"

    async with httpx.AsyncClient(timeout=30) as client:
        if http_method == "GET":
            r = await client.get(url, params=params, headers=headers)
        else:
            r = await client.post(url, data=params, headers=headers)

    data = r.json()
    log.info(f"Zadarma {method}: {data}")
    return data


async def make_call(phone: str, call_id: str) -> dict:
    """
    Инициирует исходящий звонок через Zadarma.
    Zadarma сначала звонит нам (на SIP), мы отвечаем,
    потом соединяет с пациентом.
    """
    params = {
        "from": ZADARMA_NUMBER,
        "to": phone,
        "sip": ZADARMA_NUMBER,
        # Webhook для событий звонка
        "callBack": f"{BASE_URL}/autocall/event",
    }
    return await zadarma_request("/v1/request/callback/", params, "POST")


# ─── TTS helper (импортируем из voice_agent) ─────────────────────────────────

async def tts(text: str) -> bytes:
    """gTTS — бесплатный Google TTS."""
    loop = asyncio.get_event_loop()

    def _sync():
        try:
            from gtts import gTTS
            buf = io.BytesIO()
            gTTS(text=text, lang="ru", slow=False).write_to_fp(buf)
            return buf.getvalue()
        except Exception as e:
            log.error(f"TTS error: {e}")
            return b""

    return await loop.run_in_executor(None, _sync)


async def stt(audio_bytes: bytes) -> str:
    """OpenAI Whisper STT."""
    from openai import AsyncOpenAI
    key = os.getenv("OPENAI_API_KEY", "")
    if not key:
        return ""
    client = AsyncOpenAI(api_key=key)
    buf = io.BytesIO(audio_bytes)
    buf.name = "audio.mp3"
    try:
        r = await client.audio.transcriptions.create(
            model="whisper-1", file=buf, language="ru"
        )
        return r.text.strip()
    except Exception as e:
        log.error(f"STT error: {e}")
        return ""


async def ai_reply(call_state: dict, user_text: str) -> tuple[str, bool]:
    """Claude генерирует ответ. Возвращает (текст, нужно_завершить)."""
    from anthropic import AsyncAnthropic
    claude = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))

    history = call_state.setdefault("history", [])
    history.append({"role": "user", "content": user_text})

    call_type = call_state.get("call_type", "confirm")
    patient   = call_state.get("patient_name", "пациент")
    appt_date = call_state.get("date", "")
    appt_time = call_state.get("time", "")

    if call_type == "confirm":
        task = f"Ты звонишь {patient}, чтобы подтвердить запись {appt_date} в {appt_time}. Узнай придёт ли."
    elif call_type == "review":
        task = f"Ты звонишь {patient} чтобы узнать как прошёл приём. Спроси оценку 1-5."
    else:
        task = f"Ты звонишь {patient} чтобы напомнить о записи или предложить запись."

    system = f"""Ты голосовой помощник стоматологии Аура, тебя зовут Алина.
Говоришь коротко — 1-2 предложения. Как живой человек, пациент не должен знать что ты AI.
Задача: {task}
Если пациент подтвердил/отказался/оценил — вежливо попрощайся."""

    r = await claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=150,
        system=system,
        messages=history[-10:],
    )
    reply = r.content[0].text
    history.append({"role": "assistant", "content": reply})

    end_words = ["до свидания", "всего доброго", "до встречи", "пока", "удачи"]
    should_end = any(w in reply.lower() for w in end_words)
    return reply, should_end


# ─── Уведомление в Telegram ───────────────────────────────────────────────────

async def notify(text: str):
    if not BOT_TOKEN or not ADMIN_TG_ID:
        return
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": ADMIN_TG_ID, "text": text, "parse_mode": "Markdown"}
        )


# ─── FastAPI роутер для Zadarma событий ──────────────────────────────────────

from fastapi import APIRouter
router = APIRouter(prefix="/autocall")


@router.post("/event")
async def zadarma_event(request: Request, background_tasks: BackgroundTasks):
    """
    Zadarma присылает события звонка: CALL_START, CALL_END, RECORD_READY.
    """
    form = await request.form()
    event     = form.get("event", "")
    call_id   = form.get("call_id", "")
    phone     = form.get("caller_id", form.get("called_did", ""))
    status    = form.get("disposition", "")
    recording = form.get("record_url", "")

    log.info(f"Zadarma event: {event} | call={call_id} | phone={phone} | status={status}")

    if event == "CALL_END" and recording:
        # Звонок завершён — анализируем запись
        background_tasks.add_task(_process_recording, call_id, phone, recording)

    elif event == "CALL_END" and status != "answered":
        # Не ответили
        state = _active_calls.pop(call_id, {})
        name = state.get("patient_name", phone)
        await notify(f"📵 {name} не взял трубку\nНомер: {phone}")

    return {"status": "ok"}


@router.post("/audio")
async def zadarma_audio(request: Request):
    """
    Если Zadarma поддерживает стриминг аудио (IVR mode) —
    принимаем чанк, распознаём, отвечаем аудио.
    """
    form = await request.form()
    call_id    = form.get("call_id", "")
    audio_file = form.get("audio")

    if not call_id or call_id not in _active_calls:
        return Response(content=b"", media_type="audio/mpeg")

    state = _active_calls[call_id]

    # Первый запрос — отправляем приветствие
    if not state.get("greeted"):
        state["greeted"] = True
        name = state.get("patient_name", "пациент")
        call_type = state.get("call_type", "confirm")

        if call_type == "confirm":
            greeting = (f"Здравствуйте, {name}! Это клиника Аура. "
                       f"Звоним подтвердить вашу запись "
                       f"{state.get('date','')} в {state.get('time','')}. "
                       f"Вы придёте?")
        elif call_type == "review":
            greeting = (f"Здравствуйте, {name}! Это клиника Аура. "
                       f"Вы недавно были у нас. Как прошёл приём?")
        else:
            greeting = f"Здравствуйте, {name}! Это клиника Аура, чем могу помочь?"

        state["history"] = [{"role": "assistant", "content": greeting}]
        audio = await tts(greeting)
        return Response(content=audio, media_type="audio/mpeg")

    # Распознаём речь пациента
    if audio_file:
        audio_bytes = await audio_file.read()
        user_text = await stt(audio_bytes)
        log.info(f"[{call_id}] Пациент: {user_text}")

        if user_text.strip():
            reply_text, should_end = await ai_reply(state, user_text)
            log.info(f"[{call_id}] Алина: {reply_text}")

            audio = await tts(reply_text)

            if should_end:
                _active_calls.pop(call_id, None)
                # Итог в Telegram
                history = state.get("history", [])
                turns = len([m for m in history if m["role"] == "user"])
                await notify(
                    f"✅ Звонок завершён\n"
                    f"Пациент: {state.get('patient_name','?')} ({state.get('phone','?')})\n"
                    f"Реплик: {turns}\n"
                    f"Тип: {state.get('call_type','?')}"
                )

            return Response(content=audio, media_type="audio/mpeg")

    return Response(content=b"", media_type="audio/mpeg")


async def _process_recording(call_id: str, phone: str, recording_url: str):
    """Скачивает запись, транскрибирует, анализирует."""
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.get(recording_url)
            if r.status_code != 200:
                return
            audio = r.content

        text = await stt(audio)
        if not text:
            return

        state = _active_calls.pop(call_id, {})
        name = state.get("patient_name", phone)

        # Краткий анализ
        from anthropic import AsyncAnthropic
        claude = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
        r2 = await claude.messages.create(
            model="claude-sonnet-4-6", max_tokens=200,
            messages=[{"role": "user", "content":
                f"Звонок пациенту {name}. Транскрипция:\n{text}\n\n"
                f"1 предложение: что решили?"}]
        )
        summary = r2.content[0].text

        await notify(
            f"📞 Итог звонка: {name} ({phone})\n\n"
            f"📝 {text[:400]}\n\n"
            f"💡 {summary}"
        )
    except Exception as e:
        log.error(f"Recording analysis error: {e}")


# ─── Планировщик автодозвонов ─────────────────────────────────────────────────

async def schedule_calls_for_tomorrow(db_path: str):
    """
    Берёт из БД пациентов с записью на завтра и звонит им.
    Вызывается из основного бота каждый день в 15:00.
    """
    import aiosqlite
    tomorrow = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        rows = await db.execute_fetchall(
            """SELECT DISTINCT patient, doctor, day, period
               FROM visits
               WHERE day = ? AND src IN ('shift','clean','zp')
               AND patient IS NOT NULL AND patient != ''""",
            (tomorrow,)
        )

    if not rows:
        log.info("Нет записей на завтра для обзвона")
        return

    await notify(f"📋 Начинаю обзвон: {len(rows)} пациентов на {tomorrow}")

    for row in rows:
        patient = row["patient"]
        doctor  = row["doctor"]
        # Пробуем найти номер телефона (если хранится)
        phone = await _get_patient_phone(patient, db_path)
        if not phone:
            continue

        call_id = f"auto_{patient}_{int(time.time())}"
        _active_calls[call_id] = {
            "patient_name": patient,
            "phone": phone,
            "call_type": "confirm",
            "date": tomorrow,
            "time": "",
            "doctor": doctor,
        }

        result = await make_call(phone, call_id)
        log.info(f"Call to {patient} ({phone}): {result}")
        await asyncio.sleep(30)  # Пауза между звонками


async def _get_patient_phone(patient_name: str, db_path: str) -> Optional[str]:
    """Ищет телефон пациента в БД."""
    import aiosqlite
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        row = await db.execute_fetchone(
            "SELECT phone FROM patients WHERE name LIKE ? LIMIT 1",
            (f"%{patient_name}%",)
        )
        return row["phone"] if row else None


# ─── Ручной запуск звонка из бота ────────────────────────────────────────────

async def call_patient(phone: str, patient_name: str,
                       call_type: str = "confirm",
                       date_str: str = "", time_str: str = "") -> bool:
    """
    Вызывается из Telegram-бота когда admin нажимает 'Позвонить пациенту'.
    Возвращает True если звонок инициирован успешно.
    """
    if not ZADARMA_KEY:
        log.warning("ZADARMA_KEY не установлен")
        return False

    call_id = f"manual_{phone}_{int(time.time())}"
    _active_calls[call_id] = {
        "patient_name": patient_name,
        "phone": phone,
        "call_type": call_type,
        "date": date_str,
        "time": time_str,
    }

    result = await make_call(phone, call_id)
    success = result.get("status") == "success"

    if success:
        await notify(f"📤 Звоним {patient_name} ({phone})\nТип: {call_type}")
    else:
        log.error(f"Call failed: {result}")

    return success
