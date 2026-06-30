"""
Менеджер исходящих и входящих звонков для Алины.

ИСХОДЯЩИЕ (список от администратора):
  1. Админ присылает список в Telegram (имя + телефон)
  2. Заdarma инициирует звонок каждому
  3. Когда пациент берёт трубку → Zadarma отдаёт запись
  4. Алина анализирует запись → следующий ход → новый звонок с ответом

ВХОДЯЩИЕ:
  Zadarma перенаправляет входящий → webhook → Алина отвечает через IVR.

Настройка Zadarma (один раз в личном кабинете):
  Настройки → Переадресация → Webhook → https://ВАШ_ДОМЕН/alina/event

Переменные Railway:
  ZADARMA_KEY, ZADARMA_SECRET, ZADARMA_NUMBER
"""

import os
import re
import io
import time
import asyncio
import logging
import base64
from dataclasses import dataclass, field
from typing import Optional

import httpx
from fastapi import APIRouter, Request, BackgroundTasks, Form
from fastapi.responses import Response

log = logging.getLogger("call_queue")

ZADARMA_KEY    = os.getenv("ZADARMA_KEY", "")
ZADARMA_SECRET = os.getenv("ZADARMA_SECRET", "")
ZADARMA_NUMBER = os.getenv("ZADARMA_NUMBER", "")
BASE_URL       = os.getenv("BASE_URL", "https://auraai-bot-production.up.railway.app")
ADMIN_TG_ID    = os.getenv("ADMIN_ID", "6766016614")
BOT_TOKEN      = os.getenv("BOT_TOKEN", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")


# ─────────────────────────────────────────────────────────────────────────────
# Структуры данных
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CallTask:
    phone:      str
    name:       str
    note:       str = ""           # причина звонка
    call_type:  str = "inbound"   # inbound / confirm / review / return
    status:     str = "pending"   # pending / calling / done / failed / no_answer
    zadarma_id: str = ""
    result:     str = ""          # кратко что решили


@dataclass
class CallQueue:
    tasks:      list[CallTask] = field(default_factory=list)
    active:     bool = False
    results:    list[str] = field(default_factory=list)
    notify_fn:  object = None     # async fn(text) для Telegram-уведомлений


# Единственная очередь (одна клиника)
_queue = CallQueue()

# Активные разговоры: zadarma_call_id → состояние Алины
_active: dict[str, dict] = {}


# ─────────────────────────────────────────────────────────────────────────────
# Парсер списка
# ─────────────────────────────────────────────────────────────────────────────

_PHONE_RE = re.compile(r"(\+?[78]\d{10}|\+\d{10,14})")

def parse_call_list(text: str) -> list[CallTask]:
    """
    Парсит список в любом разумном формате:

      +79991234567 Иванова Мария — болит зуб
      89991234568, Петров Иван, подтвердить запись
      Кузнецова Анна +7 999 111-22-33

    Каждая строка = один пациент.
    """
    tasks = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # Ищем телефон
        pm = _PHONE_RE.search(line)
        if not pm:
            continue
        phone_raw = pm.group(1).strip()
        phone = _norm_phone(phone_raw)

        # Всё что не телефон — имя + заметка
        rest = (line[:pm.start()] + line[pm.end():]).strip(" ,;—-–")
        # Разделяем имя от заметки по тире или запятой
        parts = re.split(r"[—–\-]{1,2}|,\s*(?=[А-ЯЁA-Z])", rest, maxsplit=1)
        name = parts[0].strip() if parts else "Пациент"
        note = parts[1].strip() if len(parts) > 1 else ""

        # Определяем тип звонка по ключевым словам в заметке
        nl = note.lower() + name.lower()
        if any(w in nl for w in ("подтвер", "запис", "напомн")):
            call_type = "confirm"
        elif any(w in nl for w in ("отзыв", "как прошло", "впечатл")):
            call_type = "review"
        elif any(w in nl for w in ("давно", "верн", "напомн о клин")):
            call_type = "return"
        else:
            call_type = "inbound"

        tasks.append(CallTask(phone=phone, name=name, note=note, call_type=call_type))
    return tasks


def _norm_phone(p: str) -> str:
    digits = re.sub(r"\D", "", p)
    if len(digits) == 11 and digits[0] in ("7", "8"):
        return "+7" + digits[1:]
    if len(digits) == 10:
        return "+7" + digits
    return "+" + digits


# ─────────────────────────────────────────────────────────────────────────────
# Zadarma API
# ─────────────────────────────────────────────────────────────────────────────

import hmac, hashlib

def _zd_sign(method: str, params: dict) -> str:
    param_str = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    data = method + param_str + hashlib.md5(param_str.encode()).hexdigest()
    return base64.b64encode(
        hmac.new(ZADARMA_SECRET.encode(), data.encode(), hashlib.sha1).digest()
    ).decode()


async def _zd_request(method: str, params: dict = None, http_method: str = "POST") -> dict:
    if not ZADARMA_KEY:
        return {"status": "error", "message": "ZADARMA_KEY не задан"}
    params = params or {}
    sign = _zd_sign(method, params)
    headers = {"Authorization": f"{ZADARMA_KEY}:{sign}"}
    async with httpx.AsyncClient(timeout=20) as client:
        if http_method == "GET":
            r = await client.get(f"https://api.zadarma.com{method}", params=params, headers=headers)
        else:
            r = await client.post(f"https://api.zadarma.com{method}", data=params, headers=headers)
    try:
        return r.json()
    except Exception:
        return {"status": "error", "raw": r.text[:200]}


async def zadarma_call(phone: str, call_id: str) -> dict:
    """Инициирует исходящий звонок через Zadarma callback API."""
    return await _zd_request("/v1/request/callback/", {
        "from":     ZADARMA_NUMBER,
        "to":       phone,
        "sip":      ZADARMA_NUMBER,
        "callBack": f"{BASE_URL}/alina/event",
    })


# ─────────────────────────────────────────────────────────────────────────────
# TTS / STT (используем admin_agent)
# ─────────────────────────────────────────────────────────────────────────────

async def _tts(text: str) -> bytes:
    from admin_agent import tts
    return await tts(text)


async def _stt(audio_bytes: bytes) -> str:
    from admin_agent import stt
    return await stt(audio_bytes, "mp3")


async def _alina(call_id: str, user_text: str, call_type: str, name: str, phone: str, note: str):
    from admin_agent import alina_reply, _calls
    if call_id not in _calls:
        from admin_agent import _greeting
        greeting = _greeting(call_type, name, "", "")
        _calls[call_id] = {
            "call_type": call_type,
            "name": name,
            "phone": phone,
            "history": [{"role": "assistant", "content": greeting}],
            "booked": None,
        }
        if note:
            _calls[call_id]["history"].append({"role": "user", "content": f"[Контекст: {note}]"})
            _calls[call_id]["history"].append({"role": "assistant", "content": "Понял, учту."})
    return await alina_reply(call_id, user_text)


# ─────────────────────────────────────────────────────────────────────────────
# Телеграм-уведомления
# ─────────────────────────────────────────────────────────────────────────────

async def _notify(text: str):
    if not BOT_TOKEN or not ADMIN_TG_ID:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={"chat_id": ADMIN_TG_ID, "text": text, "parse_mode": "Markdown"}
            )
    except Exception as e:
        log.error(f"TG notify: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Очередь исходящих звонков
# ─────────────────────────────────────────────────────────────────────────────

def load_queue(tasks: list[CallTask], notify_fn=None):
    """Загружает новый список. Сбрасывает предыдущий если он завершён."""
    global _queue
    _queue = CallQueue(tasks=tasks, notify_fn=notify_fn)


async def start_queue():
    """Запускает обзвон списка по очереди."""
    global _queue
    if _queue.active:
        return
    _queue.active = True
    total = len(_queue.tasks)
    await _notify(f"📋 Начинаю обзвон: {total} человек")

    for i, task in enumerate(_queue.tasks, 1):
        task.status = "calling"
        call_id = f"q_{task.phone}_{int(time.time())}"
        _active[call_id] = {
            "task": task,
            "turn": 0,
        }

        if ZADARMA_KEY:
            result = await zadarma_call(task.phone, call_id)
            ok = result.get("status") == "success"
        else:
            # Нет телефонии — симулируем
            ok = False
            task.status = "failed"
            task.result = "нет ZADARMA_KEY"

        if ok:
            await _notify(f"📞 [{i}/{total}] Звоню {task.name} ({task.phone})...")
        else:
            task.status = "failed"
            task.result = result.get("message", "ошибка")
            await _notify(f"❌ [{i}/{total}] {task.name} ({task.phone}) — {task.result}")

        # Пауза между звонками чтобы не спамить
        await asyncio.sleep(45)

    _queue.active = False
    await _send_queue_summary()


async def _send_queue_summary():
    done    = [t for t in _queue.tasks if t.status == "done"]
    failed  = [t for t in _queue.tasks if t.status == "failed"]
    no_ans  = [t for t in _queue.tasks if t.status == "no_answer"]

    lines = [f"📋 *Итоги обзвона* ({len(_queue.tasks)} чел.)\n"]
    if done:
        lines.append(f"✅ Дозвонились: {len(done)}")
        for t in done:
            lines.append(f"  • {t.name}: {t.result or '—'}")
    if no_ans:
        lines.append(f"📵 Не ответили: {len(no_ans)}")
        for t in no_ans:
            lines.append(f"  • {t.name} ({t.phone})")
    if failed:
        lines.append(f"❌ Ошибки: {len(failed)}")
        for t in failed:
            lines.append(f"  • {t.name}: {t.result}")

    await _notify("\n".join(lines))


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI router — Zadarma webhooks + входящие
# ─────────────────────────────────────────────────────────────────────────────

router = APIRouter(prefix="/alina")


@router.post("/event")
async def zadarma_event(request: Request, background_tasks: BackgroundTasks):
    """
    Zadarma шлёт сюда события: CALL_START, CALL_END, RECORD_READY.
    Настрой в личном кабинете Zadarma:
      Настройки → Уведомления → Webhook → https://ВАШ_ДОМЕН/alina/event
    """
    try:
        form = await request.form()
        data = dict(form)
    except Exception:
        data = await request.json()

    event    = data.get("event", data.get("call_state", ""))
    call_id  = data.get("call_id", data.get("pbx_call_id", ""))
    phone    = data.get("caller_id", data.get("called_did", data.get("to", "")))
    status   = data.get("disposition", data.get("call_status", ""))
    rec_url  = data.get("link", data.get("record_url", ""))

    log.info(f"Zadarma event: {event} | {call_id} | {phone} | {status}")

    # ── Входящий звонок начался ──
    if event in ("CALL_START", "start") and call_id not in _active:
        # Новый входящий — создаём задачу
        task = CallTask(phone=phone, name="Пациент", call_type="inbound")
        _active[call_id] = {"task": task, "turn": 0}
        await _notify(f"📞 Входящий звонок от {phone}")

    # ── Звонок завершён, запись готова ──
    if rec_url and call_id in _active:
        background_tasks.add_task(_process_recording, call_id, phone, rec_url)

    # ── Не ответили ──
    if status in ("no answer", "busy", "failed") or event in ("CALL_END_NO_ANSWER",):
        if call_id in _active:
            task = _active[call_id]["task"]
            task.status = "no_answer"
            task.result = "не ответил"
            _active.pop(call_id, None)
            await _notify(f"📵 {task.name} ({phone}) не ответил")

    return {"status": "ok"}


@router.post("/inbound")
async def inbound_start(request: Request):
    """
    Альтернативный webhook для входящего — сразу отдаём приветствие Алины.
    Формат ответа зависит от вашей АТС (Zadarma, Asterisk, etc.)
    Возвращает MP3 с приветствием.
    """
    try:
        form = await request.form()
        data = dict(form)
    except Exception:
        data = {}

    phone   = data.get("caller_id", data.get("from", ""))
    call_id = data.get("call_id", f"in_{phone}_{int(time.time())}")

    from admin_agent import _greeting, _calls
    greeting = _greeting("inbound", "пациент", "", "")
    _calls[call_id] = {
        "call_type": "inbound",
        "name": "",
        "phone": phone,
        "history": [{"role": "assistant", "content": greeting}],
        "booked": None,
    }
    _active[call_id] = {"task": CallTask(phone=phone, name="Пациент", call_type="inbound"), "turn": 0}

    audio = await _tts(greeting)
    await _notify(f"📞 Входящий от {phone} — Алина ответила")
    return Response(content=audio, media_type="audio/mpeg")


@router.post("/audio")
async def inbound_audio(request: Request, background_tasks: BackgroundTasks):
    """
    АТС прислала аудио фразы пациента → отвечаем аудио Алины.
    Принимает: multipart/form-data или JSON с audio_b64.
    """
    content_type = request.headers.get("content-type", "")
    if "multipart" in content_type or "form" in content_type:
        form = await request.form()
        call_id = form.get("call_id", "")
        audio_file = form.get("audio")
        audio_bytes = await audio_file.read() if audio_file else b""
        user_text = await _stt(audio_bytes) if audio_bytes else ""
    else:
        body = await request.json()
        call_id = body.get("call_id", "")
        raw = body.get("audio_b64", "")
        audio_bytes = base64.b64decode(raw) if raw else b""
        user_text = body.get("text") or (await _stt(audio_bytes) if audio_bytes else "")

    if call_id not in _active:
        return Response(content=b"", media_type="audio/mpeg")

    state = _active[call_id]
    task  = state["task"]

    if not user_text.strip():
        audio = await _tts("Простите, не расслышала. Повторите пожалуйста.")
        return Response(content=audio, media_type="audio/mpeg")

    log.info(f"[{call_id}] Пациент: {user_text!r}")

    reply, end_call, booking = await _alina(
        call_id, user_text, task.call_type, task.name, task.phone, task.note
    )

    if booking:
        task.status = "done"
        task.result = f"записан: {booking.get('time_pref','?')}"
        await _notify(
            f"🦷 *Запись от Алины*\n"
            f"👤 {booking.get('name') or task.name}\n"
            f"📞 {booking.get('phone') or task.phone}\n"
            f"🕐 {booking.get('time_pref','?')}\n"
            f"🔖 {booking.get('issue','?')}"
        )

    if end_call:
        if task.status == "calling":
            task.status = "done"
            task.result = "разговор завершён"
        _active.pop(call_id, None)

    log.info(f"[{call_id}] Алина: {reply!r}")
    audio = await _tts(reply)
    return Response(content=audio, media_type="audio/mpeg")


async def _process_recording(call_id: str, phone: str, rec_url: str):
    """Скачивает запись, транскрибирует через Whisper, анализирует итог."""
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.get(rec_url)
            if r.status_code != 200:
                return
            audio = r.content

        text = await _stt(audio)
        if not text:
            return

        state = _active.pop(call_id, {})
        task  = state.get("task")
        if not task:
            return

        # Краткий итог через Claude
        from admin_agent import claude as anthropic_client
        resp = await anthropic_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=120,
            messages=[{"role": "user", "content":
                f"Звонок пациенту {task.name} ({task.phone}).\n"
                f"Тип: {task.call_type}. Заметка: {task.note}.\n"
                f"Транскрипция:\n{text}\n\n"
                f"Одно предложение: что решили? Записался / не пришёл / перезвонит?"}]
        )
        summary = resp.content[0].text
        task.status = "done"
        task.result = summary

        await _notify(
            f"📞 *Итог разговора*\n"
            f"👤 {task.name} ({phone})\n"
            f"💬 {text[:300]}\n\n"
            f"✅ {summary}"
        )
    except Exception as e:
        log.error(f"Recording error {call_id}: {e}")
