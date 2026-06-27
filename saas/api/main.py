"""
SaaS API — мультиарендная платформа для AI-агентов клиник.
Каждая клиника = отдельный tenant с своим ботом и голосовым агентом.
"""

import os
import uuid
import hashlib
import asyncio
import aiosqlite
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

app = FastAPI(title="AuraAI Platform", version="1.0.0")

DB_PATH = os.getenv("SAAS_DB", "/tmp/saas.db")


# ─── Модели ──────────────────────────────────────────────────────────────────

class ClinicRegister(BaseModel):
    name: str           # Название клиники
    phone: str          # Телефон владельца
    email: str
    password: str

class ClinicLogin(BaseModel):
    email: str
    password: str

class AgentConfig(BaseModel):
    agent_name: str = "Алина"
    clinic_greeting: str = ""      # Своё приветствие
    work_hours: str = "9:00-20:00"
    services: str = ""             # Список услуг через запятую
    telephony_type: str = "none"   # calibri | voximplant | none
    telephony_api_url: str = ""
    telephony_api_key: str = ""
    tg_bot_token: str = ""
    yandex_api_key: str = ""
    yandex_folder_id: str = ""


# ─── База данных ──────────────────────────────────────────────────────────────

async def get_db():
    return await aiosqlite.connect(DB_PATH)

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS clinics (
                id          TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                phone       TEXT,
                email       TEXT UNIQUE NOT NULL,
                pwd_hash    TEXT NOT NULL,
                api_key     TEXT UNIQUE NOT NULL,
                plan        TEXT DEFAULT 'free',
                created_at  TEXT DEFAULT (datetime('now')),
                active      INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS agent_configs (
                clinic_id       TEXT PRIMARY KEY REFERENCES clinics(id),
                agent_name      TEXT DEFAULT 'Алина',
                clinic_greeting TEXT DEFAULT '',
                work_hours      TEXT DEFAULT '9:00-20:00',
                services        TEXT DEFAULT '',
                telephony_type  TEXT DEFAULT 'none',
                telephony_url   TEXT DEFAULT '',
                telephony_key   TEXT DEFAULT '',
                tg_bot_token    TEXT DEFAULT '',
                yandex_api_key  TEXT DEFAULT '',
                yandex_folder_id TEXT DEFAULT '',
                updated_at      TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS call_logs (
                id          TEXT PRIMARY KEY,
                clinic_id   TEXT REFERENCES clinics(id),
                phone       TEXT,
                call_type   TEXT,
                duration_sec INTEGER DEFAULT 0,
                result      TEXT,
                created_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS call_stats (
                clinic_id   TEXT REFERENCES clinics(id),
                date        TEXT,
                total_calls INTEGER DEFAULT 0,
                confirmed   INTEGER DEFAULT 0,
                cancelled   INTEGER DEFAULT 0,
                reviews_avg REAL DEFAULT 0,
                PRIMARY KEY (clinic_id, date)
            );
        """)
        await db.commit()


# ─── Auth ────────────────────────────────────────────────────────────────────

def hash_pwd(pwd: str) -> str:
    return hashlib.sha256(pwd.encode()).hexdigest()

def make_api_key() -> str:
    return f"aura_{uuid.uuid4().hex}"

async def get_clinic(api_key: str = Header(alias="X-Api-Key")) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        row = await db.execute_fetchone(
            "SELECT * FROM clinics WHERE api_key = ? AND active = 1", (api_key,)
        )
        if not row:
            raise HTTPException(401, "Invalid API key")
        return dict(row)


# ─── Регистрация / Вход ───────────────────────────────────────────────────────

@app.post("/register")
async def register(data: ClinicRegister):
    clinic_id = str(uuid.uuid4())
    api_key   = make_api_key()

    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO clinics(id,name,phone,email,pwd_hash,api_key) VALUES(?,?,?,?,?,?)",
                (clinic_id, data.name, data.phone, data.email,
                 hash_pwd(data.password), api_key)
            )
            await db.execute(
                "INSERT INTO agent_configs(clinic_id) VALUES(?)", (clinic_id,)
            )
            await db.commit()
        except Exception as e:
            if "UNIQUE" in str(e):
                raise HTTPException(409, "Email already registered")
            raise HTTPException(500, str(e))

    return {
        "clinic_id": clinic_id,
        "api_key": api_key,
        "message": f"Клиника '{data.name}' зарегистрирована. Сохрани api_key!"
    }


@app.post("/login")
async def login(data: ClinicLogin):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        row = await db.execute_fetchone(
            "SELECT * FROM clinics WHERE email=? AND pwd_hash=? AND active=1",
            (data.email, hash_pwd(data.password))
        )
        if not row:
            raise HTTPException(401, "Неверный email или пароль")
        r = dict(row)
    return {"api_key": r["api_key"], "name": r["name"], "plan": r["plan"]}


# ─── Настройка агента ────────────────────────────────────────────────────────

@app.get("/config")
async def get_config(clinic: dict = Depends(get_clinic)):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        row = await db.execute_fetchone(
            "SELECT * FROM agent_configs WHERE clinic_id=?", (clinic["id"],)
        )
        return dict(row) if row else {}

@app.put("/config")
async def update_config(data: AgentConfig, clinic: dict = Depends(get_clinic)):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE agent_configs SET
                agent_name=?, clinic_greeting=?, work_hours=?, services=?,
                telephony_type=?, telephony_url=?, telephony_key=?,
                tg_bot_token=?, yandex_api_key=?, yandex_folder_id=?,
                updated_at=datetime('now')
            WHERE clinic_id=?
        """, (data.agent_name, data.clinic_greeting, data.work_hours,
              data.services, data.telephony_type, data.telephony_api_url,
              data.telephony_api_key, data.tg_bot_token,
              data.yandex_api_key, data.yandex_folder_id, clinic["id"]))
        await db.commit()
    return {"status": "ok"}


# ─── Статистика ────────────────────────────────────────────────────────────

@app.get("/stats")
async def get_stats(clinic: dict = Depends(get_clinic)):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Итого звонков
        total = await db.execute_fetchone(
            "SELECT COUNT(*) as cnt FROM call_logs WHERE clinic_id=?", (clinic["id"],)
        )
        # За 7 дней
        week = await db.execute_fetchone(
            "SELECT COUNT(*) as cnt FROM call_logs WHERE clinic_id=? AND created_at >= date('now','-7 days')",
            (clinic["id"],)
        )
        # Подтверждённые
        confirmed = await db.execute_fetchone(
            "SELECT COUNT(*) as cnt FROM call_logs WHERE clinic_id=? AND result='confirmed'",
            (clinic["id"],)
        )

        return {
            "total_calls": dict(total)["cnt"],
            "calls_last_7d": dict(week)["cnt"],
            "confirmed": dict(confirmed)["cnt"],
            "clinic_name": clinic["name"],
            "plan": clinic["plan"],
        }


# ─── Лог звонков ────────────────────────────────────────────────────────────

@app.get("/calls")
async def get_calls(limit: int = 50, clinic: dict = Depends(get_clinic)):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await db.execute_fetchall(
            "SELECT * FROM call_logs WHERE clinic_id=? ORDER BY created_at DESC LIMIT ?",
            (clinic["id"], limit)
        )
        return [dict(r) for r in rows]


# ─── Webhook от голосового агента ────────────────────────────────────────────

@app.post("/webhook/call-result")
async def call_result_webhook(request, clinic: dict = Depends(get_clinic)):
    """Голосовой агент присылает результат звонка."""
    body = await request.json()
    log_id = str(uuid.uuid4())
    today  = datetime.now().strftime("%Y-%m-%d")

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO call_logs(id,clinic_id,phone,call_type,duration_sec,result) VALUES(?,?,?,?,?,?)",
            (log_id, clinic["id"], body.get("phone"), body.get("call_type"),
             body.get("duration_sec", 0), body.get("result"))
        )

        # Обновляем дневную статистику
        result = body.get("result", "")
        confirmed_delta = 1 if result == "confirmed" else 0
        cancelled_delta = 1 if result == "cancelled" else 0

        await db.execute("""
            INSERT INTO call_stats(clinic_id, date, total_calls, confirmed, cancelled)
            VALUES(?,?,1,?,?)
            ON CONFLICT(clinic_id,date) DO UPDATE SET
                total_calls = total_calls + 1,
                confirmed   = confirmed + ?,
                cancelled   = cancelled + ?
        """, (clinic["id"], today, confirmed_delta, cancelled_delta,
              confirmed_delta, cancelled_delta))

        await db.commit()

    return {"status": "logged", "log_id": log_id}


@app.on_event("startup")
async def startup():
    await init_db()
