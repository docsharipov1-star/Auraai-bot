"""
Голосовой AI-агент для клиники.
Принимает звонки через webhook → STT → Claude → TTS → аудио ответ.

Запуск: uvicorn voice_agent:app --host 0.0.0.0 --port 8001
"""

import os
import io
import json
import asyncio
import logging
import tempfile
import base64
from typing import Optional
from datetime import datetime

import httpx
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks, Form
from fastapi.responses import JSONResponse, Response
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("voice_agent")

app = FastAPI(title="AuraAI Voice Agent")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY", "")   # для Whisper STT
ADMIN_TG_ID       = os.getenv("ADMIN_ID", "6766016614")
BOT_TOKEN         = os.getenv("BOT_TOKEN", "")
BASE_URL          = os.getenv("BASE_URL", "https://auraai-bot-production.up.railway.app")

openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

anthropic = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

# Контексты разговоров: call_id → список сообщений
_conversations: dict[str, list] = {}

# Системный промпт агента клиники
CLINIC_SYSTEM = """Ты — голосовой помощник стоматологической клиники Аура.
Твоё имя Алина. Говоришь коротко и по делу, как живой человек.
Пациент не должен понимать что ты AI.

Твои задачи:
1. Подтверждение записи — уточни придёт ли пациент
2. Сбор отзыва — узнай как прошёл приём (1-5 звёзд)
3. Запись на приём — помоги выбрать удобное время
4. Ответы на вопросы — режим работы, услуги, цены

Правила:
- Говори естественно, используй паузы ("Понял", "Хорошо", "Конечно")
- Не говори длинные монологи — жди реакции пациента
- Если вопрос сложный — предложи перезвонить врачу
- Всегда заканчивай разговор вежливо

Клиника работает: Пн-Сб 9:00-20:00, Вс 10:00-18:00"""


# ─── STT: речь → текст (OpenAI Whisper) ─────────────────────────────────────

async def speech_to_text(audio_bytes: bytes, format: str = "ogg") -> str:
    """Конвертирует аудио в текст через OpenAI Whisper. $0.006/мин."""
    if not openai_client:
        return "[тест: нет OPENAI_API_KEY]"

    # Whisper принимает файл-объект
    audio_file = io.BytesIO(audio_bytes)
    audio_file.name = f"audio.{format}"

    try:
        result = await openai_client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            language="ru",
        )
        return result.text.strip()
    except Exception as e:
        log.error(f"Whisper STT error: {e}")
        return ""


# ─── AI: генерация ответа ────────────────────────────────────────────────────

async def generate_reply(call_id: str, user_text: str, context: dict = None) -> str:
    """Генерирует ответ агента через Claude."""
    if call_id not in _conversations:
        _conversations[call_id] = []

    # Добавляем контекст первым сообщением если есть
    if context and not _conversations[call_id]:
        ctx_text = json.dumps(context, ensure_ascii=False)
        _conversations[call_id].append({
            "role": "user",
            "content": f"[Контекст звонка]: {ctx_text}"
        })
        _conversations[call_id].append({
            "role": "assistant",
            "content": "Понял, начинаю разговор."
        })

    _conversations[call_id].append({"role": "user", "content": user_text})

    response = await anthropic.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=200,
        system=CLINIC_SYSTEM,
        messages=_conversations[call_id],
    )

    reply = response.content[0].text
    _conversations[call_id].append({"role": "assistant", "content": reply})

    # Ограничиваем историю 20 сообщениями
    if len(_conversations[call_id]) > 20:
        _conversations[call_id] = _conversations[call_id][-20:]

    return reply


# ─── TTS: текст → речь (Google TTS — бесплатно) ─────────────────────────────

async def text_to_speech(text: str) -> bytes:
    """Конвертирует текст в аудио через Google TTS (gTTS). Бесплатно."""
    try:
        # gTTS работает синхронно — запускаем в executor
        loop = asyncio.get_event_loop()
        audio_bytes = await loop.run_in_executor(None, _gtts_sync, text)
        return audio_bytes
    except Exception as e:
        log.error(f"TTS error: {e}")
        return b""

def _gtts_sync(text: str) -> bytes:
    """Синхронная обёртка для gTTS."""
    try:
        from gtts import gTTS
        buf = io.BytesIO()
        tts = gTTS(text=text, lang="ru", slow=False)
        tts.write_to_fp(buf)
        return buf.getvalue()
    except ImportError:
        log.error("gTTS не установлен: pip install gtts")
        return b""


# ─── Уведомление в Telegram ──────────────────────────────────────────────────

async def notify_admin(text: str):
    """Отправляет уведомление администратору в Telegram."""
    if not BOT_TOKEN or not ADMIN_TG_ID:
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(url, json={"chat_id": ADMIN_TG_ID, "text": text})


# ─── Webhook endpoints ────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "AuraAI Voice Agent"}


@app.post("/call/start")
async def call_start(request: Request, background_tasks: BackgroundTasks):
    """
    Вызывается телефонией когда пациент взял трубку.
    Тело: { call_id, phone, call_type, patient_name, date, time }
    Ответ: { greeting_text, greeting_audio_base64 }
    """
    body = await request.json()
    call_id    = body.get("call_id", f"call_{datetime.now().timestamp()}")
    call_type  = body.get("call_type", "confirm")   # confirm | review | info
    name       = body.get("patient_name", "пациент")
    date       = body.get("date", "")
    time_      = body.get("time", "")
    phone      = body.get("phone", "")

    # Формируем первое приветствие
    if call_type == "confirm":
        greeting = f"Здравствуйте, {name}! Это клиника Аура. " \
                   f"Звоним подтвердить вашу запись {date} в {time_}. " \
                   f"Вы планируете прийти?"
    elif call_type == "review":
        greeting = f"Здравствуйте, {name}! Это клиника Аура. " \
                   f"Вы недавно были у нас. Как вы оцениваете качество приёма?"
    else:
        greeting = f"Здравствуйте, {name}! Это клиника Аура, чем могу помочь?"

    # Инициализируем контекст
    _conversations[call_id] = []
    context = {"call_type": call_type, "name": name, "date": date,
               "time": time_, "phone": phone}

    # Добавляем приветствие в историю
    _conversations[call_id].append({"role": "assistant", "content": greeting})

    # Генерируем аудио
    audio = await text_to_speech(greeting)

    background_tasks.add_task(
        notify_admin,
        f"📞 Новый звонок\nПациент: {name} ({phone})\nТип: {call_type}"
    )

    log.info(f"Call started: {call_id} | {name} | {call_type}")

    return {
        "call_id": call_id,
        "greeting_text": greeting,
        "greeting_audio_base64": base64.b64encode(audio).decode() if audio else "",
        "status": "active"
    }


@app.post("/call/audio")
async def call_audio(request: Request, background_tasks: BackgroundTasks):
    """
    Вызывается телефонией когда пациент сказал что-то.
    Поддерживает JSON (наш формат) и form-urlencoded (Callibri).
    """
    content_type = request.headers.get("content-type", "")

    # Callibri присылает form-urlencoded — перенаправляем в callibri_webhook
    if "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
        return await callibri_webhook(request, background_tasks)

    body = await request.json()
    call_id = body.get("call_id", "")

    if not call_id:
        raise HTTPException(400, "call_id required")

    # Получаем текст: либо готовый, либо из аудио
    if "text" in body:
        user_text = body["text"]
    elif "audio_base64" in body:
        audio_bytes = base64.b64decode(body["audio_base64"])
        user_text = await speech_to_text(audio_bytes, body.get("format", "oggopus"))
    else:
        raise HTTPException(400, "text or audio_base64 required")

    log.info(f"[{call_id}] Пациент: {user_text}")

    if not user_text.strip():
        # Тишина — просим повторить
        reply = "Простите, не расслышала. Повторите пожалуйста."
        audio = await text_to_speech(reply)
        return {
            "reply_text": reply,
            "reply_audio_base64": base64.b64encode(audio).decode() if audio else "",
            "end_call": False
        }

    # Генерируем ответ
    reply = await generate_reply(call_id, user_text)

    # Определяем — нужно ли заканчивать звонок
    end_phrases = ["до свидания", "всего доброго", "до встречи", "пока"]
    end_call = any(p in reply.lower() for p in end_phrases)

    audio = await text_to_speech(reply)
    log.info(f"[{call_id}] Агент: {reply} | end={end_call}")

    return {
        "reply_text": reply,
        "reply_audio_base64": base64.b64encode(audio).decode() if audio else "",
        "end_call": end_call
    }


@app.post("/call/end")
async def call_end(request: Request, background_tasks: BackgroundTasks):
    """
    Вызывается телефонией когда звонок завершён.
    Тело: { call_id, duration_sec, result }
    """
    body = await request.json()
    call_id  = body.get("call_id", "")
    duration = body.get("duration_sec", 0)
    result   = body.get("result", "unknown")

    # Достаём историю разговора
    history = _conversations.pop(call_id, [])
    turns = len([m for m in history if m["role"] == "user"])

    log.info(f"Call ended: {call_id} | {duration}s | {turns} turns | {result}")

    background_tasks.add_task(
        notify_admin,
        f"📵 Звонок завершён\nID: {call_id}\nДлительность: {duration}с\n"
        f"Реплик: {turns}\nРезультат: {result}"
    )

    return {"status": "ok", "call_id": call_id}


@app.post("/call/test")
async def call_test(request: Request):
    """
    Тестовый endpoint — симулирует разговор без телефонии.
    Тело: { message, call_id? }
    """
    body = await request.json()
    call_id = body.get("call_id", "test_call")
    message = body.get("message", "Здравствуйте")

    reply = await generate_reply(call_id, message)

    return {
        "call_id": call_id,
        "user": message,
        "agent": reply,
        "history_length": len(_conversations.get(call_id, []))
    }


# ─── Исходящие звонки (через любую телефонию с API) ─────────────────────────

@app.post("/call/outbound")
async def call_outbound(request: Request, background_tasks: BackgroundTasks):
    """
    Инициирует исходящий звонок через Калибри/любую телефонию.
    Тело: { phone, patient_name, call_type, date?, time?, telephony_api_url, telephony_api_key }
    """
    body = await request.json()
    phone       = body.get("phone", "")
    name        = body.get("patient_name", "пациент")
    call_type   = body.get("call_type", "confirm")
    date        = body.get("date", "")
    time_       = body.get("time", "")
    tel_url     = body.get("telephony_api_url", "")
    tel_key     = body.get("telephony_api_key", "")
    webhook_url = body.get("webhook_url", f"{BASE_URL}/call/audio")

    if not phone:
        raise HTTPException(400, "phone required")

    # Если нет URL телефонии — просто логируем (mock режим)
    if not tel_url:
        log.info(f"[MOCK] Исходящий звонок: {phone} | {name} | {call_type}")
        background_tasks.add_task(
            notify_admin,
            f"📤 [MOCK] Исходящий звонок\n{name} ({phone})\nТип: {call_type}"
        )
        return {"status": "mock", "phone": phone, "call_type": call_type}

    # Реальный вызов телефонии
    call_id = f"out_{phone}_{int(datetime.now().timestamp())}"
    payload = {
        "phone": phone,
        "call_id": call_id,
        "webhook_url": webhook_url or f"https://your-domain.com/call/audio",
        "custom_data": {
            "call_type": call_type,
            "patient_name": name,
            "date": date,
            "time": time_,
        }
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            headers = {"Authorization": f"Bearer {tel_key}"}
            r = await client.post(tel_url, json=payload, headers=headers)
            r.raise_for_status()
            return {"status": "calling", "call_id": call_id, "response": r.json()}
    except Exception as e:
        log.error(f"Telephony error: {e}")
        raise HTTPException(502, f"Telephony error: {e}")


# ─── Callibri webhook ────────────────────────────────────────────────────────

@app.post("/callibri/webhook")
async def callibri_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
):
    """
    Callibri присылает данные о звонке после его завершения.
    Формат: application/x-www-form-urlencoded
    Все параметры принимаем и анализируем через AI.
    """
    # Принимаем form-encoded данные
    form = await request.form()
    data = dict(form)

    phone        = data.get("phone", "")
    name         = data.get("name", "Пациент")
    duration     = data.get("billsec", data.get("duration", "0"))
    call_status  = data.get("call_status", "")
    event_type   = data.get("event_type", "")
    recording    = data.get("link_download", "")
    source       = data.get("source", "")
    lid_id       = data.get("lid_id", "")
    is_lid       = data.get("is_lid", "")
    region       = data.get("region", "")
    comment      = data.get("comment", "")
    date         = data.get("date_project", data.get("date", ""))

    log.info(f"Callibri webhook: {phone} | {call_status} | {duration}s | lid={is_lid}")

    # Анализируем звонок через AI если есть запись
    analysis = ""
    transcript = ""
    if recording:
        background_tasks.add_task(
            _analyze_callibri_call,
            phone, name, recording, duration, call_status, is_lid, source
        )

    # Немедленное уведомление в Telegram
    status_emoji = "✅" if call_status in ("Отвечен", "answered") else "❌"
    lid_emoji    = "🎯 ЛИД" if str(is_lid) in ("1", "true", "True") else ""

    msg = (
        f"📞 Звонок из Callibri {lid_emoji}\n"
        f"Пациент: {name} ({phone})\n"
        f"Статус: {status_emoji} {call_status}\n"
        f"Длительность: {duration} сек\n"
        f"Источник: {source}\n"
        f"Регион: {region}"
    )
    if comment:
        msg += f"\nКомментарий: {comment}"
    if recording:
        msg += f"\n🎙 Запись: анализирую..."

    background_tasks.add_task(notify_admin, msg)

    return {"status": "ok"}


async def _analyze_callibri_call(
    phone: str, name: str, recording_url: str,
    duration: str, call_status: str, is_lid: str, source: str
):
    """
    Скачивает запись, транскрибирует через Whisper,
    Алина анализирует и даёт конкретную рекомендацию что делать дальше.
    """
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.get(recording_url)
            if r.status_code != 200:
                log.error(f"Не удалось скачать запись: {recording_url}")
                return
            audio_bytes = r.content

        transcript = await speech_to_text(audio_bytes, "mp3")
        if not transcript:
            await notify_admin(f"🎙 Запись {name} ({phone}) — не удалось распознать речь")
            return

        log.info(f"Транскрипция ({phone}): {transcript[:200]}")

        # Алина анализирует звонок как умный администратор
        prompt = f"""Ты — Алина, старший администратор стоматологии «Аура».
Прослушала запись звонка и анализируешь её для владельца клиники.

Данные звонка:
• Пациент: {name or 'неизвестен'} ({phone})
• Источник: {source or 'прямой звонок'}
• Длительность: {duration} сек
• Статус: {call_status}
• Это новый лид: {'да' if str(is_lid) in ('1','true','True') else 'нет'}

Транскрипция разговора:
{transcript}

Дай анализ строго по пунктам (коротко, по-деловому):

1. 🎯 Цель звонка (1 строка)
2. 💬 Итог разговора (записался / не записался / перезвонит / другое)
3. ⚡ Действие (что сделать ПРЯМО СЕЙЧАС — перезвонить / записать / ничего)
4. 💡 Что сказать если перезванивать (готовая фраза для администратора, 1-2 предложения)
5. ⭐ Потенциал (горячий лид / тёплый / холодный / уже клиент)"""

        response = await anthropic.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}]
        )
        analysis = response.content[0].text

        lid_emoji = "🎯 *ЛИД*" if str(is_lid) in ("1", "true", "True") else ""
        dur_sec = int(duration or 0)
        dur_str = f"{dur_sec // 60}:{dur_sec % 60:02d}" if dur_sec else "—"

        await notify_admin(
            f"📞 *Разбор звонка* {lid_emoji}\n"
            f"👤 {name or 'Пациент'} · {phone}\n"
            f"⏱ {dur_str} · {source or 'прямой звонок'}\n\n"
            f"{analysis}\n\n"
            f"📝 *Транскрипция:*\n_{transcript[:600]}_"
        )

    except Exception as e:
        log.error(f"Ошибка анализа звонка: {e}")
        await notify_admin(f"⚠️ Не удалось проанализировать звонок {phone}: {e}")
