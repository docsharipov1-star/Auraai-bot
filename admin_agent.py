"""
Виртуальный администратор клиники «Аура» — Алина.

Голос: OpenAI TTS, модель nova (нежный женский голос).
Мозг: Claude Sonnet с многошаговым сценарием продаж.
Память: история разговора в памяти процесса (per call_id).

Сценарии:
  inbound   — входящий звонок (пациент сам позвонил)
  confirm   — исходящий, подтвердить запись
  review    — исходящий, получить отзыв после приёма
  return    — исходящий, позвонить пациенту который давно не приходил

FastAPI endpoints (совместимы с voice_agent.py):
  POST /admin/call/start   — начало звонка, возвращает приветствие
  POST /admin/call/audio   — фраза пациента → ответ агента
  POST /admin/call/end     — завершение звонка
  POST /admin/call/test    — тест без телефонии (текст → текст)
"""

import os
import io
import re
import json
import asyncio
import logging
import base64
from datetime import datetime, date, timedelta
from typing import Optional

import httpx
from fastapi import APIRouter, Request, BackgroundTasks, HTTPException
from anthropic import AsyncAnthropic

log = logging.getLogger("admin_agent")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY", "")
ADMIN_TG_ID       = os.getenv("ADMIN_ID", "6766016614")
BOT_TOKEN         = os.getenv("BOT_TOKEN", "")
BASE_URL          = os.getenv("BASE_URL", "https://auraai-bot-production.up.railway.app")
CLINIC_PHONE      = os.getenv("CLINIC_PHONE", "")      # номер клиники для ответа пациентам

claude = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

# call_id → {"history": [...], "state": str, "booked": dict|None, "name": str, "phone": str}
_calls: dict[str, dict] = {}


# ─────────────────────────────────────────────────────────────────────────────
# СИСТЕМНЫЙ ПРОМПТ — АЛИНА
# ─────────────────────────────────────────────────────────────────────────────

ALINA_SYSTEM = """Ты — Алина, виртуальный администратор стоматологической клиники «Аура».

ГОЛОС И СТИЛЬ:
• Говоришь мягко, тепло, с заботой — как внимательный человек, а не робот
• Короткие фразы — 1-2 предложения максимум, потом ждёшь ответа
• Паузы и переходы: «Понятно», «Конечно», «Хорошо», «Замечательно»
• Никогда не торопишь и не давишь на пациента
• Пациент не должен догадаться что ты AI

ИНФОРМАЦИЯ О КЛИНИКЕ:
• Режим работы: Пн–Сб 9:00–20:00, Вс 10:00–18:00
• Услуги: лечение кариеса, протезирование, имплантация, отбеливание, детская стоматология, ортодонтия (брекеты, элайнеры), гигиена и чистка
• Первичная консультация — БЕСПЛАТНО
• Оплата: наличные, карта, рассрочка 0%
• Врачи: терапевт, хирург, ортопед, ортодонт, детский стоматолог
• Адрес и телефон сообщи если спросят: «Уточню и перезвоним — чтобы не ошибиться»

СЦЕНАРИЙ ПРОДАЖ (ВХОДЯЩИЙ ЗВОНОК):
1. ПРИВЕТСТВИЕ → представься, спроси чем помочь
2. ВЫЯВЛЕНИЕ → «Что вас беспокоит?» — слушай, уточняй
3. КВАЛИФИКАЦИЯ → «Когда в последний раз были у стоматолога?» «Острая боль или профилактика?»
4. ПРЕДЛОЖЕНИЕ → назови подходящую услугу + «Первичная консультация бесплатная»
5. РАБОТА С ВОЗРАЖЕНИЯМИ (см. ниже)
6. ЗАПИСЬ → «Когда вам удобнее — утром или после обеда?» → уточни имя и номер телефона → подтверди

РАБОТА С ВОЗРАЖЕНИЯМИ:
• «Дорого» → «Понимаю. У нас есть рассрочка на 0% — это удобно. Хотите подберём вариант?»
• «Боюсь» → «Это очень понятно. У нас врачи работают с анестезией, вы ничего не почувствуете. Многие пациенты потом удивляются как было комфортно.»
• «Подумаю» → «Конечно, не тороплю. Могу записать предварительно — если передумаете, просто позвоните отменить.»
• «Нет времени» → «Понимаю, все очень заняты. Мы работаем в субботу до 20:00 — может, найдётся удобный слот?»
• «У меня есть стоматолог» → «Замечательно! Если понадобится второе мнение или что-то срочное — мы всегда рядом.»

КАК ЗАПИСЫВАТЬ:
Когда пациент готов записаться — уточни:
1. Имя
2. Номер телефона (если входящий — он уже есть)
3. Удобное время (утро / день / вечер, будни / выходные)
4. Что беспокоит (кратко)

После получения данных скажи: «Отлично! Записала вас. Наш администратор свяжется с вами в течение часа для подтверждения точного времени.»

КОГДА ЗАКАНЧИВАТЬ:
• Пациент сказал «до свидания», «спасибо», «пока» — попрощайся тепло
• Вопрос решён (записали / получили информацию) — подведи итог и попрощайся
• Пациент просит перезвонить — «Конечно, передам врачу. Хорошего дня!»

ЗАПРЕЩЕНО:
• Называть конкретные цены (только «уточнит врач на консультации»)
• Гарантировать результаты лечения
• Говорить что ты AI или робот — если спросят, скажи «Я администратор клиники»
• Говорить длинными монологами"""


CONFIRM_SYSTEM = """Ты — Алина, администратор клиники «Аура». Позвонила подтвердить запись пациента.

Задача: мягко уточнить придёт ли пациент, и если нет — предложить перенести.

Сценарий:
1. Поздоровайся, назови себя и клинику
2. Напомни дату и время записи
3. Спроси: «Вы планируете прийти?»
4. Если ДА → «Отлично! Ждём вас. Если что-то изменится — позвоните нам заранее.»
5. Если НЕТ / СОМНЕВАЕТСЯ → «Понимаю. Хотите перенести? Скажите удобное время — запишу.»
6. Попрощайся тепло

Говори коротко, не давить. Пациент не должен чувствовать давления."""


REVIEW_SYSTEM = """Ты — Алина, администратор клиники «Аура». Звонишь узнать впечатление после приёма.

Задача: получить честный отзыв и при негативе — урегулировать.

Сценарий:
1. Поздоровайся, напомни что пациент был на приёме
2. Спроси: «Как всё прошло? Как вы себя чувствуете?»
3. Если ХОРОШО → «Замечательно! Будем рады видеть вас снова. Если порекомендуете нас — будем очень благодарны.»
4. Если ПЛОХО / ЖАЛОБА → «Очень жаль. Расскажите подробнее — передам главному врачу лично. Мы это исправим.»
5. Предложи записаться на следующий визит если уместно

Тон: тёплый, искренний, без формальностей."""


RETURN_SYSTEM = """Ты — Алина, администратор клиники «Аура». Звонишь пациенту который давно не был.

Задача: напомнить о клинике и мотивировать записаться.

Сценарий:
1. Поздоровайся, напомни о клинике
2. «Давно вас не видели — хотели узнать как вы?»
3. Напомни что профилактика раз в полгода важна
4. Предложи запись: «Первичная консультация у нас бесплатная — когда вам удобно?»

Не давить. Если не интересует — «Хорошо, если понадобится — мы здесь. Всего доброго!»"""


# ─────────────────────────────────────────────────────────────────────────────
# TTS — OpenAI nova (нежный женский голос)
# ─────────────────────────────────────────────────────────────────────────────

async def tts(text: str) -> bytes:
    """
    Преобразует текст в речь через OpenAI TTS.
    Голос: nova — тёплый женский, хорошо говорит по-русски.
    Скорость: 0.92 — чуть медленнее для ощущения мягкости.
    Fallback: gTTS если нет OPENAI_API_KEY.
    """
    if OPENAI_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(
                    "https://api.openai.com/v1/audio/speech",
                    headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                    json={
                        "model": "tts-1",
                        "voice": "nova",       # самый нежный женский голос
                        "input": text,
                        "speed": 0.92,         # чуть медленнее = мягче
                        "response_format": "mp3",
                    }
                )
                if r.status_code == 200:
                    return r.content
                log.error(f"OpenAI TTS {r.status_code}: {r.text[:200]}")
        except Exception as e:
            log.error(f"OpenAI TTS error: {e}")

    # Fallback — gTTS (бесплатно, но роботизированный)
    return await _gtts_fallback(text)


async def _gtts_fallback(text: str) -> bytes:
    loop = asyncio.get_event_loop()
    def _sync():
        try:
            from gtts import gTTS
            buf = io.BytesIO()
            gTTS(text=text, lang="ru", slow=False).write_to_fp(buf)
            return buf.getvalue()
        except Exception as e:
            log.error(f"gTTS: {e}")
            return b""
    return await loop.run_in_executor(None, _sync)


# ─────────────────────────────────────────────────────────────────────────────
# STT — OpenAI Whisper
# ─────────────────────────────────────────────────────────────────────────────

async def stt(audio_bytes: bytes, fmt: str = "mp3") -> str:
    if not OPENAI_API_KEY:
        return ""
    try:
        buf = io.BytesIO(audio_bytes)
        buf.name = f"audio.{fmt}"
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                files={"file": (buf.name, buf, f"audio/{fmt}")},
                data={"model": "whisper-1", "language": "ru"},
            )
            if r.status_code == 200:
                return r.json().get("text", "").strip()
            log.error(f"Whisper {r.status_code}: {r.text[:200]}")
    except Exception as e:
        log.error(f"STT error: {e}")
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# AI — генерация ответа Алины
# ─────────────────────────────────────────────────────────────────────────────

def _system_for(call_type: str) -> str:
    return {
        "confirm": CONFIRM_SYSTEM,
        "review":  REVIEW_SYSTEM,
        "return":  RETURN_SYSTEM,
    }.get(call_type, ALINA_SYSTEM)


async def alina_reply(call_id: str, user_text: str) -> tuple[str, bool, dict | None]:
    """
    Генерирует ответ Алины.
    Возвращает (текст, завершить_звонок, данные_записи_или_None).
    """
    state = _calls.get(call_id, {})
    history = state.get("history", [])
    call_type = state.get("call_type", "inbound")

    history.append({"role": "user", "content": user_text})

    # Вспомогательный промпт для извлечения данных записи
    extraction_note = (
        "\n\n[ВАЖНО: Если в этом сообщении пациент назвал своё имя или подтвердил запись — "
        "в конце своего ответа добавь JSON в формате: "
        "###BOOKING:{\"name\":\"...\",\"phone\":\"...\",\"time_pref\":\"...\",\"issue\":\"...\"}### "
        "Если данных нет — не добавляй ничего.]"
    )

    r = await claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=250,
        system=_system_for(call_type) + extraction_note,
        messages=history[-16:],
    )

    raw = r.content[0].text
    history.append({"role": "assistant", "content": raw})
    state["history"] = history[-20:]
    _calls[call_id] = state

    # Извлекаем данные записи если есть
    booking = None
    text = raw
    m = re.search(r"###BOOKING:(\{.*?\})###", raw, re.DOTALL)
    if m:
        try:
            booking = json.loads(m.group(1))
            # Подставляем телефон из контекста если не назвал
            if not booking.get("phone") and state.get("phone"):
                booking["phone"] = state["phone"]
            if not booking.get("name") and state.get("name"):
                booking["name"] = state["name"]
        except Exception:
            pass
        text = raw[:m.start()].strip()

    # Определяем завершение звонка
    end_words = ["до свидания", "всего доброго", "до встречи", "хорошего дня", "удачи вам", "пока!"]
    end_call = any(w in text.lower() for w in end_words)

    return text, end_call, booking


# ─────────────────────────────────────────────────────────────────────────────
# Первое приветствие по типу звонка
# ─────────────────────────────────────────────────────────────────────────────

def _greeting(call_type: str, name: str, appt_date: str, appt_time: str) -> str:
    if call_type == "confirm":
        date_str = f"{appt_date} в {appt_time}" if appt_time else appt_date
        return (f"Здравствуйте, {name}! Это Алина из клиники Аура. "
                f"Звоню напомнить о вашей записи {date_str}. "
                f"Вы планируете прийти?")

    if call_type == "review":
        return (f"Здравствуйте, {name}! Это Алина из клиники Аура. "
                f"Вы недавно были у нас на приёме — хотела узнать как всё прошло и как вы себя чувствуете?")

    if call_type == "return":
        return (f"Здравствуйте, {name}! Это Алина из стоматологии Аура. "
                f"Давно вас не видели — хотела узнать как вы, всё ли хорошо?")

    # inbound — пациент сам позвонил
    return "Стоматология Аура, добрый день! Меня зовут Алина, чем могу помочь?"


# ─────────────────────────────────────────────────────────────────────────────
# Уведомление в Telegram
# ─────────────────────────────────────────────────────────────────────────────

async def _notify(text: str):
    if not BOT_TOKEN or not ADMIN_TG_ID:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={"chat_id": ADMIN_TG_ID, "text": text, "parse_mode": "Markdown"}
            )
    except Exception as e:
        log.error(f"Telegram notify: {e}")


async def _notify_booking(call_id: str, booking: dict):
    name    = booking.get("name") or "Пациент"
    phone   = booking.get("phone") or "—"
    time_p  = booking.get("time_pref") or "не уточнено"
    issue   = booking.get("issue") or "не указано"
    await _notify(
        f"🦷 *Новая запись от Алины*\n\n"
        f"👤 {name}\n"
        f"📞 {phone}\n"
        f"🕐 Когда удобно: {time_p}\n"
        f"🔖 Вопрос: {issue}\n\n"
        f"_Позвони подтвердить точное время_"
    )


async def _notify_call_end(call_id: str, duration: int, booked: bool):
    state   = _calls.get(call_id, {})
    name    = state.get("name", "Пациент")
    phone   = state.get("phone", "—")
    ctype   = state.get("call_type", "inbound")
    turns   = len([m for m in state.get("history", []) if m["role"] == "user"])
    result  = "✅ Записан" if booked else "💬 Разговор"
    await _notify(
        f"📵 Звонок завершён\n"
        f"{result} | {name} ({phone})\n"
        f"Тип: {ctype} | {turns} реплик | {duration}с"
    )


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI router
# ─────────────────────────────────────────────────────────────────────────────

router = APIRouter(prefix="/admin")


@router.post("/call/start")
async def call_start(request: Request, background_tasks: BackgroundTasks):
    """
    Начало звонка. Принимает:
      { call_id, call_type, patient_name, phone, date?, time? }
    Возвращает:
      { call_id, greeting_text, greeting_audio_b64 }
    """
    body       = await request.json()
    call_id    = body.get("call_id") or f"call_{int(datetime.now().timestamp())}"
    call_type  = body.get("call_type", "inbound")
    name       = body.get("patient_name", "")
    phone      = body.get("phone", "")
    appt_date  = body.get("date", "")
    appt_time  = body.get("time", "")

    greeting = _greeting(call_type, name or "пациент", appt_date, appt_time)

    _calls[call_id] = {
        "call_type": call_type,
        "name":      name,
        "phone":     phone,
        "history":   [{"role": "assistant", "content": greeting}],
        "booked":    None,
        "started":   datetime.now().isoformat(),
    }

    audio = await tts(greeting)
    background_tasks.add_task(
        _notify,
        f"📞 Звонок | {name or 'входящий'} ({phone}) | {call_type}"
    )

    log.info(f"Call start: {call_id} | {call_type} | {name} {phone}")
    return {
        "call_id":            call_id,
        "greeting_text":      greeting,
        "greeting_audio_b64": base64.b64encode(audio).decode() if audio else "",
        "status":             "active",
    }


@router.post("/call/audio")
async def call_audio(request: Request, background_tasks: BackgroundTasks):
    """
    Фраза пациента → ответ Алины.
    Принимает: { call_id, text? } или { call_id, audio_b64, format? }
    Возвращает: { reply_text, reply_audio_b64, end_call, booked }
    """
    body    = await request.json()
    call_id = body.get("call_id", "")

    if call_id not in _calls:
        raise HTTPException(404, "Звонок не найден — сначала /admin/call/start")

    # Получаем текст
    if "text" in body:
        user_text = body["text"].strip()
    elif "audio_b64" in body:
        audio_bytes = base64.b64decode(body["audio_b64"])
        user_text = await stt(audio_bytes, body.get("format", "mp3"))
    else:
        raise HTTPException(400, "Нужно поле text или audio_b64")

    log.info(f"[{call_id}] Пациент: {user_text!r}")

    if not user_text:
        reply = "Простите, не расслышала. Пожалуйста, повторите."
        return {
            "reply_text":      reply,
            "reply_audio_b64": base64.b64encode(await tts(reply)).decode(),
            "end_call":        False,
            "booked":          False,
        }

    reply, end_call, booking = await alina_reply(call_id, user_text)

    # Сохраняем данные записи
    if booking:
        _calls[call_id]["booked"] = booking
        background_tasks.add_task(_notify_booking, call_id, booking)

    audio = await tts(reply)
    log.info(f"[{call_id}] Алина: {reply!r} | end={end_call} | booked={bool(booking)}")

    return {
        "reply_text":      reply,
        "reply_audio_b64": base64.b64encode(audio).decode() if audio else "",
        "end_call":        end_call,
        "booked":          bool(_calls[call_id].get("booked")),
    }


@router.post("/call/end")
async def call_end(request: Request, background_tasks: BackgroundTasks):
    """
    Конец звонка. Принимает: { call_id, duration_sec? }
    """
    body     = await request.json()
    call_id  = body.get("call_id", "")
    duration = int(body.get("duration_sec") or 0)

    state  = _calls.pop(call_id, {})
    booked = bool(state.get("booked"))

    background_tasks.add_task(_notify_call_end, call_id, duration, booked)
    log.info(f"Call end: {call_id} | {duration}s | booked={booked}")

    return {"status": "ok", "call_id": call_id, "booked": booked}


@router.post("/call/test")
async def call_test(request: Request):
    """
    Тест без телефонии — текст входит, текст выходит.
    Принимает: { message, call_id?, call_type?, patient_name?, phone? }
    """
    body      = await request.json()
    call_id   = body.get("call_id", "test_001")
    message   = body.get("message", "Здравствуйте")
    call_type = body.get("call_type", "inbound")
    name      = body.get("patient_name", "")
    phone     = body.get("phone", "")

    # Инициализируем если новый
    if call_id not in _calls:
        greeting = _greeting(call_type, name or "пациент", "", "")
        _calls[call_id] = {
            "call_type": call_type,
            "name":      name,
            "phone":     phone,
            "history":   [{"role": "assistant", "content": greeting}],
            "booked":    None,
        }
        return {
            "call_id":   call_id,
            "alina":     greeting,
            "end_call":  False,
            "booked":    False,
        }

    reply, end_call, booking = await alina_reply(call_id, message)
    if booking:
        _calls[call_id]["booked"] = booking

    return {
        "call_id":  call_id,
        "user":     message,
        "alina":    reply,
        "end_call": end_call,
        "booked":   bool(_calls[call_id].get("booked")),
        "booking":  booking,
    }


@router.get("/call/test/audio")
async def test_tts(request: Request):
    """Проверить голос Алины. ?text=Привет"""
    text  = request.query_params.get("text", "Здравствуйте! Это Алина из клиники Аура. Чем могу помочь?")
    audio = await tts(text)
    from fastapi.responses import Response
    return Response(content=audio, media_type="audio/mpeg")
