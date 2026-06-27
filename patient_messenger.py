"""
Пишет пациентам в Telegram по номеру телефона — без предварительного контакта.
Использует личный аккаунт (Telethon MTProto), не бота.

Запуск: python3 patient_messenger.py
"""

import os
import asyncio
import logging
from datetime import date, timedelta, datetime
from anthropic import AsyncAnthropic

from telethon import TelegramClient, events
from telethon.tl.functions.contacts import ImportContactsRequest, DeleteContactsRequest
from telethon.tl.types import InputPhoneContact

log = logging.getLogger("patient_messenger")

API_ID   = int(os.getenv("TG_API_ID", "39654408"))
API_HASH = os.getenv("TG_API_HASH", "")
SESSION  = "aura_session"

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ADMIN_TG_ID       = int(os.getenv("ADMIN_ID", "6766016614"))

claude = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

# Активные диалоги: phone → история сообщений
_dialogs: dict[str, list] = {}
_phone_to_entity: dict[str, any] = {}

SYSTEM_PROMPT = """Ты — администратор стоматологической клиники Аура, тебя зовут Алина.
Пишешь пациентам в Telegram коротко и по-человечески.
Пациент не должен понимать что ты AI.

Правила:
- Пиши коротко, 1-2 предложения
- Будь вежливой и тёплой
- Если пациент подтвердил/отказался — поблагодари и попрощайся
- Если просит перенести — скажи что передашь врачу и попрощайся
- Если задаёт вопросы о лечении — отвечай кратко, при сложных вопросах предлагай позвонить"""


async def find_patient_on_telegram(client: TelegramClient, phone: str) -> any:
    """Ищет пациента в Telegram по номеру телефона."""
    # Нормализуем номер
    phone = phone.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if not phone.startswith("+"):
        phone = "+" + phone

    try:
        # Временно добавляем в контакты чтобы найти
        contact = InputPhoneContact(client_id=0, phone=phone, first_name="Пациент", last_name="")
        result = await client(ImportContactsRequest([contact]))

        if result.users:
            user = result.users[0]
            # Удаляем из контактов после поиска
            await client(DeleteContactsRequest(id=[user]))
            log.info(f"Найден в Telegram: {phone} → {user.first_name} (id={user.id})")
            return user
        else:
            log.info(f"Не найден в Telegram: {phone}")
            return None
    except Exception as e:
        log.error(f"Ошибка поиска {phone}: {e}")
        return None


async def generate_message(context: dict, user_reply: str = None) -> tuple[str, bool]:
    """Генерирует сообщение через Claude. Возвращает (текст, завершить_диалог)."""
    phone     = context.get("phone", "")
    name      = context.get("patient_name", "пациент")
    call_type = context.get("call_type", "confirm")
    appt_date = context.get("date", "завтра")
    appt_time = context.get("time", "")
    doctor    = context.get("doctor", "")

    history = _dialogs.setdefault(phone, [])

    # Первое сообщение — инициируем
    if not history:
        if call_type == "confirm":
            doctor_str = f" к {doctor}" if doctor else ""
            time_str   = f" в {appt_time}" if appt_time else ""
            text = (f"Добрый день, {name}! 🦷 Это клиника Аура. "
                   f"Напоминаем о вашей записи{doctor_str} {appt_date}{time_str}. "
                   f"Вы придёте?")
        elif call_type == "review":
            text = (f"Добрый день, {name}! Это клиника Аура. "
                   f"Вы недавно были у нас на приёме. "
                   f"Как вы оцениваете качество обслуживания? 😊")
        else:
            text = f"Добрый день, {name}! Это клиника Аура, чем могу помочь?"

        history.append({"role": "assistant", "content": text})
        return text, False

    # Ответ на реплику пациента
    if user_reply:
        history.append({"role": "user", "content": user_reply})

        r = await claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=150,
            system=SYSTEM_PROMPT,
            messages=history[-10:],
        )
        reply = r.content[0].text
        history.append({"role": "assistant", "content": reply})

        # Диалог завершён если попрощались
        end_words = ["до свидания", "всего доброго", "до встречи", "пока!", "удачи", "хорошего дня"]
        is_done = any(w in reply.lower() for w in end_words)
        return reply, is_done

    return "", False


async def send_to_patient(client: TelegramClient, phone: str, context: dict) -> bool:
    """
    Находит пациента и отправляет первое сообщение.
    Возвращает True если пациент найден в Telegram.
    """
    entity = await find_patient_on_telegram(client, phone)
    if not entity:
        return False

    _phone_to_entity[phone] = entity
    context["phone"] = phone

    text, _ = await generate_message(context)
    await client.send_message(entity, text)
    log.info(f"Отправлено {context.get('patient_name','?')} ({phone}): {text[:80]}")
    return True


async def handle_incoming(client: TelegramClient, event):
    """Обрабатывает входящие ответы от пациентов."""
    msg = event.message
    if msg.out:
        return

    sender = await msg.get_sender()
    if not sender:
        return

    # Находим телефон по entity
    phone = None
    for p, entity in _phone_to_entity.items():
        if entity.id == sender.id:
            phone = p
            break

    if not phone or phone not in _dialogs:
        return

    context = {"phone": phone}
    user_text = msg.text or ""
    log.info(f"Ответ от {phone}: {user_text}")

    reply_text, is_done = await generate_message(context, user_text)

    if reply_text:
        await client.send_message(sender, reply_text)

    if is_done:
        # Итог диалога → уведомление администратору
        history = _dialogs.pop(phone, [])
        turns = len([m for m in history if m["role"] == "user"])
        summary = "\n".join(
            f"{'← Пациент' if m['role']=='user' else '→ Алина'}: {m['content']}"
            for m in history
        )
        try:
            await client.send_message(ADMIN_TG_ID,
                f"✅ Диалог с {phone} завершён ({turns} ответов)\n\n{summary[:800]}"
            )
        except Exception:
            pass
        _phone_to_entity.pop(phone, None)


async def run_daily_confirmations(db_path: str):
    """
    Главная задача: каждый день пишет пациентам с записью на завтра.
    Запускается планировщиком из auraai_bot_v3.py в 15:00.
    """
    import aiosqlite
    tomorrow = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        rows = await db.execute_fetchall(
            """SELECT DISTINCT patient, doctor, day
               FROM visits
               WHERE day = ? AND src IN ('shift','clean','zp')
               AND patient IS NOT NULL AND patient != ''
               AND LOWER(patient) NOT LIKE '%не указан%'""",
            (tomorrow,)
        )

    if not rows:
        log.info(f"Нет пациентов на {tomorrow}")
        return

    if not API_HASH:
        log.error("TG_API_HASH не задан в переменных окружения")
        return

    async with TelegramClient(SESSION, API_ID, API_HASH) as client:
        # Слушаем входящие ответы
        client.add_event_handler(
            lambda e: handle_incoming(client, e),
            events.NewMessage(incoming=True)
        )

        # Ищем телефоны и пишем
        not_found = []
        sent_count = 0

        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            for row in rows:
                name   = row["patient"]
                doctor = row["doctor"] or ""

                # Ищем номер телефона в таблице patients
                phone_row = await db.execute_fetchone(
                    "SELECT phone FROM patients WHERE LOWER(name) LIKE LOWER(?) LIMIT 1",
                    (f"%{name.split()[0]}%",)
                )
                phone = phone_row["phone"] if phone_row else None

                if not phone:
                    not_found.append(name)
                    continue

                context = {
                    "patient_name": name,
                    "call_type": "confirm",
                    "date": tomorrow,
                    "doctor": doctor,
                }
                found = await send_to_patient(client, phone, context)
                if found:
                    sent_count += 1
                else:
                    not_found.append(f"{name} ({phone})")

                await asyncio.sleep(3)  # Пауза между сообщениями

        # Уведомляем администратора
        msg = f"📨 Обзвон на {tomorrow}\n✅ Отправлено: {sent_count}\n"
        if not_found:
            msg += f"❌ Нет в Telegram: {', '.join(not_found[:10])}"
        await client.send_message(ADMIN_TG_ID, msg)

        # Ждём ответы 2 часа
        log.info("Ожидаю ответы пациентов (2 часа)...")
        await asyncio.sleep(7200)


async def add_patient_phone(db_path: str, name: str, phone: str):
    """Сохраняет номер телефона пациента в БД."""
    import aiosqlite
    async with aiosqlite.connect(db_path) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS patients (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                name    TEXT NOT NULL,
                phone   TEXT,
                tg_id   INTEGER,
                created TEXT DEFAULT (datetime('now'))
            )
        """)
        await db.execute(
            "INSERT OR REPLACE INTO patients(name, phone) VALUES(?,?)",
            (name, phone)
        )
        await db.commit()


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) >= 3 and sys.argv[1] == "send":
        # Тест: python3 patient_messenger.py send +79991234567 "Иванов Иван"
        phone = sys.argv[2]
        name  = sys.argv[3] if len(sys.argv) > 3 else "пациент"

        async def test_send():
            async with TelegramClient(SESSION, API_ID, API_HASH) as client:
                ctx = {"patient_name": name, "call_type": "confirm",
                       "date": "завтра", "time": "14:00", "doctor": "Мостиева"}
                found = await send_to_patient(client, phone, ctx)
                print("✅ Найден и отправлено" if found else "❌ Нет в Telegram")

        asyncio.run(test_send())
    else:
        print("Использование: python3 patient_messenger.py send +79991234567 'Имя Пациента'")
