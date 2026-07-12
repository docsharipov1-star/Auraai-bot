"""
Система автозвонков пациентам стоматологии.

Цикл:
  +1 день  → звонок «как самочувствие?»
  +90 дней → звонок «приглашаем на гигиену»
  +180 дней → звонок «пора на осмотр»

Хранение: таблица clinic_patients в основной БД (aiosqlite).
"""

import os
import re
import json
import logging
import asyncio
from datetime import date, datetime, timedelta, timezone

import aiosqlite

log = logging.getLogger("clinic_patients")

DB_PATH = os.getenv("DB_PATH", "/app/data/auraai.db")

# Расписание звонков: (тип, дней_после_визита)
CALL_SCHEDULE = [
    ("wellbeing", 1),
    ("hygiene",  90),
    ("checkup", 180),
]

CALL_LABELS = {
    "wellbeing": "самочувствие",
    "hygiene":   "гигиена",
    "checkup":   "осмотр",
}


# ── БД ───────────────────────────────────────────────────────────────────────

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS clinic_patients (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL,
                phone       TEXT NOT NULL,
                doctor      TEXT DEFAULT '',
                visit_date  TEXT NOT NULL,
                calls_done  TEXT DEFAULT '[]',
                created_at  TEXT DEFAULT (date('now'))
            )
        """)
        await db.commit()


async def add_patient(name: str, phone: str, doctor: str = "", visit_date: date = None) -> int:
    vd = (visit_date or date.today()).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO clinic_patients (name, phone, doctor, visit_date) VALUES (?,?,?,?)",
            (name.strip(), phone.strip(), doctor.strip(), vd)
        )
        await db.commit()
        return cur.lastrowid


async def get_all_patients() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await db.execute_fetchall(
            "SELECT * FROM clinic_patients ORDER BY visit_date DESC"
        )
        return [dict(r) for r in rows]


async def mark_called(patient_id: int, call_type: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        row = await (await db.execute(
            "SELECT calls_done FROM clinic_patients WHERE id=?", (patient_id,)
        )).fetchone()
        if not row:
            return
        done = json.loads(row["calls_done"] or "[]")
        if call_type not in done:
            done.append(call_type)
        await db.execute(
            "UPDATE clinic_patients SET calls_done=? WHERE id=?",
            (json.dumps(done), patient_id)
        )
        await db.commit()


async def delete_patient(patient_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM clinic_patients WHERE id=?", (patient_id,))
        await db.commit()


# ── Нормализация телефона ──────────────────────────────────────────────────

def normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 10:
        digits = "7" + digits
    elif len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    return "+" + digits if digits else raw


# ── Скрипты звонков ───────────────────────────────────────────────────────

CALL_SCRIPTS = {
    "wellbeing": (
        "Добрый день, {name}! Это клиника Аура, звоним узнать как вы себя чувствуете "
        "после вчерашнего приёма. Всё в порядке? Нет никаких жалоб?"
    ),
    "hygiene": (
        "Добрый день, {name}! Это клиника Аура. Прошло три месяца с вашего последнего визита. "
        "Хотим напомнить: профессиональная чистка зубов каждые три месяца — это основа здоровья. "
        "Хотите записаться на гигиену? Сейчас есть свободные окна."
    ),
    "checkup": (
        "Добрый день, {name}! Это клиника Аура. Прошло уже полгода с вашего визита — "
        "самое время на профилактический осмотр. Это займёт всего 15-20 минут и поможет "
        "избежать серьёзных проблем. Запишем вас?"
    ),
}


# ── Планировщик звонков ───────────────────────────────────────────────────

async def _run_scheduled_calls():
    """Каждое утро в 10:00 МСК проверяет кому звонить сегодня."""
    from autocall import call_patient

    MSK = timezone(timedelta(hours=3))
    while True:
        now    = datetime.now(MSK)
        target = now.replace(hour=10, minute=0, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())

        try:
            await init_db()
            patients = await get_all_patients()
            today    = date.today()

            for p in patients:
                vd    = date.fromisoformat(p["visit_date"])
                done  = json.loads(p.get("calls_done") or "[]")
                delta = (today - vd).days

                for call_type, days_after in CALL_SCHEDULE:
                    if call_type in done:
                        continue
                    if delta >= days_after:
                        script = CALL_SCRIPTS[call_type].format(name=p["name"].split()[0])
                        ok = await call_patient(
                            phone        = p["phone"],
                            patient_name = p["name"],
                            call_type    = call_type,
                            date_str     = p["visit_date"],
                            time_str     = "",
                        )
                        if ok:
                            await mark_called(p["id"], call_type)
                            log.info(f"Звонок {call_type} → {p['name']} ({p['phone']})")
                        await asyncio.sleep(60)  # пауза между звонками

        except Exception as e:
            log.error(f"scheduled calls error: {e}")


def start_patient_calls(bot=None):
    asyncio.create_task(_run_scheduled_calls())
