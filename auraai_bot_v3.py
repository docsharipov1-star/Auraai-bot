"""
╔══════════════════════════════════════════════════════╗
║          AuraAI Bot v3.0 — Syntx AI Style            ║
║  Reply Keyboard + все разделы + починенные картинки  ║
╚══════════════════════════════════════════════════════╝

.env файл:
  BOT_TOKEN=...
  ANTHROPIC_KEY=sk-ant-...
  OPENAI_KEY=sk-proj-...
  DEEPSEEK_KEY=sk-...
  ADMIN_ID=6766016614
  BOT_USERNAME=GetAuraAI_bot
"""

import asyncio
import hashlib
import logging
import os
import httpx
from datetime import datetime, timedelta

import aiosqlite
import anthropic
from openai import AsyncOpenAI
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton, LabeledPrice,
    Message, PreCheckoutQuery, BufferedInputFile,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from dotenv import load_dotenv

load_dotenv()

# ══════════════════════════════════════════════════════
#  КОНФИГ
# ══════════════════════════════════════════════════════

BOT_TOKEN     = os.getenv("BOT_TOKEN", "")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_KEY", "")
OPENAI_KEY    = os.getenv("OPENAI_KEY", "")
DEEPSEEK_KEY  = os.getenv("DEEPSEEK_KEY", "")
AIML_KEY      = os.getenv("AIML_KEY", "")
ADMIN_ID      = int(os.getenv("ADMIN_ID", "0"))
BOT_USERNAME  = os.getenv("BOT_USERNAME", "GetAuraAI_bot")
DB_PATH       = "auraai.db"
FREE_CREDITS  = 100
REFERRAL_BONUS = 50

anthropic_client = None
openai_client    = None
deepseek_client  = None
kie_client       = None

PLANS = {
    "pro":  {"name": "Pro",  "emoji": "👑", "stars": 500,  "credits": 5000,  "days": 30, "description": "5 000 кредитов на 30 дней"},
    "team": {"name": "Team", "emoji": "💎", "stars": 1200, "credits": 15000, "days": 30, "description": "15 000 кредитов на 30 дней"},
}

CREDIT_PACKS = {
    "pack_500":   {"name": "500 кредитов",    "stars": 100,  "credits": 500},
    "pack_2000":  {"name": "2 000 кредитов",  "stars": 350,  "credits": 2000},
    "pack_5000":  {"name": "5 000 кредитов",  "stars": 800,  "credits": 5000},
    "pack_15000": {"name": "15 000 кредитов", "stars": 2000, "credits": 15000},
}

TEXT_MODELS = {
    "claude":   {"name": "Claude Sonnet", "emoji": "🅰", "cost": 10, "provider": "anthropic"},
    "deepseek": {"name": "DeepSeek V3",   "emoji": "🐋", "cost": 5,  "provider": "deepseek"},
    "gpt4o":    {"name": "GPT-4o",        "emoji": "✳️", "cost": 15, "provider": "openai"},
}

REFERRAL_LEVELS = {
    "user":    {"name": "Пользователь", "emoji": "👤", "percent": 10,  "description": "10% от пополнений рефералов"},
    "partner": {"name": "Партнёр",      "emoji": "🤝", "percent": 25,  "description": "25% — от 10 рефералов"},
    "blogger": {"name": "Блогер",       "emoji": "🌟", "percent": 50,  "description": "50% — назначается администратором"},
}

REFERRAL_MONTHS    = 12
MIN_WITHDRAW_STARS = 100
PARTNER_MIN_REFS   = 10

# ── Системные промпты ─────────────────────────────────
SYSTEM_PROMPTS = {
    "chat":       "Ты умный AI-ассистент. Отвечай полезно и по делу на языке пользователя.",
    "copywriter": "Ты профессиональный копирайтер. Пиши продающие тексты: лэндинги, посты, рекламу. Форматируй красиво.",
    "code":       "Ты senior-разработчик. Пиши чистый код с комментариями. Объясняй решения.",
    "seo":        "Ты SEO-специалист. Анализируй запросы, подбирай ключевые слова, пиши SEO-тексты.",
    "translate":  "Ты профессиональный переводчик. Переводи точно, сохраняй стиль оригинала.",
    "summarize":  "Ты эксперт по саммаризации. Выделяй главное, структурируй, делай краткие выводы.",
    "email":      "Ты email-маркетолог. Пиши письма: тема, превью, тело, CTA.",
    "essay":      "Ты профессиональный писатель. Пиши эссе, статьи и длинные тексты структурированно.",
    "rewrite":    "Ты редактор. Переписывай тексты улучшая стиль, грамматику и читаемость.",
    "idea":       "Ты креативный директор. Генерируй свежие идеи, концепции и решения.",
}

# ══════════════════════════════════════════════════════
#  БАЗА ДАННЫХ
# ══════════════════════════════════════════════════════

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id                  INTEGER PRIMARY KEY,
                username            TEXT, full_name TEXT,
                plan                TEXT    DEFAULT 'free',
                credits             INTEGER DEFAULT 0,
                credits_total       INTEGER DEFAULT 0,
                plan_expires        TEXT,
                ref_level           TEXT    DEFAULT 'user',
                ref_code            TEXT    UNIQUE,
                stars_balance       INTEGER DEFAULT 0,
                stars_earned_total  INTEGER DEFAULT 0,
                referrals_count     INTEGER DEFAULT 0,
                registered_at       TEXT    DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER, amount INTEGER, type TEXT,
                description TEXT, balance INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS ai_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER, tool TEXT, model TEXT,
                credits_used INTEGER, status TEXT DEFAULT 'success',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER, type TEXT, product_id TEXT,
                stars INTEGER, status TEXT DEFAULT 'completed',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER NOT NULL, referee_id INTEGER NOT NULL UNIQUE,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP, expires_at TEXT
            );
            CREATE TABLE IF NOT EXISTS referral_earnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER, referee_id INTEGER,
                payment_stars INTEGER, commission_pct INTEGER,
                credits_earned INTEGER, stars_earned INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS withdrawal_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER, stars_amount INTEGER,
                status TEXT DEFAULT 'pending', admin_note TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP, processed_at TEXT
            );
        """)
        await db.commit()

async def db_get(q, p=()):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(q, p) as c: return await c.fetchone()

async def db_all(q, p=()):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(q, p) as c: return await c.fetchall()

async def db_run(q, p=()):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(q, p); await db.commit()

async def get_user(uid): return await db_get("SELECT * FROM users WHERE id=?", (uid,))
async def get_balance(uid):
    r = await db_get("SELECT credits FROM users WHERE id=?", (uid,))
    return r["credits"] if r else 0

async def create_user(uid, username, full_name):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (id,username,full_name,credits,credits_total) VALUES (?,?,?,?,?)",
            (uid, username, full_name, FREE_CREDITS, FREE_CREDITS))
        await db.execute(
            "INSERT INTO transactions (user_id,amount,type,description,balance) VALUES (?,?,'bonus','Приветственные кредиты',?)",
            (uid, FREE_CREDITS, FREE_CREDITS))
        await db.commit()

async def add_credits(uid, amount, tx_type, desc) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT credits FROM users WHERE id=?", (uid,)) as c: row = await c.fetchone()
        cur = row["credits"] if row else 0
        new = cur + amount
        await db.execute("UPDATE users SET credits=?, credits_total=credits_total+? WHERE id=?", (new, amount, uid))
        await db.execute("INSERT INTO transactions (user_id,amount,type,description,balance) VALUES (?,?,?,?,?)", (uid, amount, tx_type, desc, new))
        await db.commit(); return new

async def use_credits(uid, tool, cost) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT credits FROM users WHERE id=?", (uid,)) as c: row = await c.fetchone()
        if not row or row["credits"] < cost: return False
        new = row["credits"] - cost
        await db.execute("UPDATE users SET credits=? WHERE id=?", (new, uid))
        await db.execute("INSERT INTO transactions (user_id,amount,type,description,balance) VALUES (?,?,'usage',?,?)", (uid, -cost, f"Инструмент: {tool}", new))
        await db.commit(); return True

async def set_plan(uid, plan, credits, days):
    expires = (datetime.now() + timedelta(days=days)).isoformat()
    await db_run("UPDATE users SET plan=?, plan_expires=? WHERE id=?", (plan, expires, uid))
    await add_credits(uid, credits, "subscription", f"Подписка {plan}")

async def log_request(uid, tool, model, cost):
    await db_run("INSERT INTO ai_requests (user_id,tool,model,credits_used) VALUES (?,?,?,?)", (uid, tool, model, cost))

# ── Рефералы ──────────────────────────────────────────
def make_ref_code(uid): return hashlib.md5(f"aura_{uid}_ref".encode()).hexdigest()[:8].upper()

async def get_or_create_ref_code(uid):
    row = await db_get("SELECT ref_code FROM users WHERE id=?", (uid,))
    if row and row["ref_code"]: return row["ref_code"]
    code = make_ref_code(uid)
    await db_run("UPDATE users SET ref_code=? WHERE id=?", (code, uid)); return code

async def get_user_by_ref_code(code): return await db_get("SELECT * FROM users WHERE ref_code=?", (code.upper(),))

async def register_referral(referrer_id, referee_id):
    if referrer_id == referee_id: return False
    if await db_get("SELECT id FROM referrals WHERE referee_id=?", (referee_id,)): return False
    expires = (datetime.now() + timedelta(days=REFERRAL_MONTHS * 30)).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO referrals (referrer_id,referee_id,expires_at) VALUES (?,?,?)", (referrer_id, referee_id, expires))
        await db.execute("UPDATE users SET referrals_count=referrals_count+1 WHERE id=?", (referrer_id,))
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT referrals_count,ref_level FROM users WHERE id=?", (referrer_id,)) as c: row = await c.fetchone()
        if row and row["referrals_count"] >= PARTNER_MIN_REFS and row["ref_level"] == "user":
            await db.execute("UPDATE users SET ref_level='partner' WHERE id=?", (referrer_id,))
        await db.commit(); return True

async def process_commission(referee_id, payment_stars):
    ref = await db_get("SELECT r.referrer_id,r.expires_at,u.ref_level FROM referrals r JOIN users u ON u.id=r.referrer_id WHERE r.referee_id=?", (referee_id,))
    if not ref: return None
    if ref["expires_at"] and datetime.now() > datetime.fromisoformat(ref["expires_at"]): return None
    referrer_id = ref["referrer_id"]; level = ref["ref_level"] or "user"
    pct = REFERRAL_LEVELS[level]["percent"]
    stars_earned = round(payment_stars * pct / 100); credits_earned = stars_earned * 10
    if stars_earned == 0: return None
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT credits FROM users WHERE id=?", (referrer_id,)) as c: row = await c.fetchone()
        cur = row["credits"] if row else 0; new = cur + credits_earned
        await db.execute("UPDATE users SET credits=?,credits_total=credits_total+?,stars_balance=stars_balance+?,stars_earned_total=stars_earned_total+? WHERE id=?", (new, credits_earned, stars_earned, stars_earned, referrer_id))
        await db.execute("INSERT INTO referral_earnings (referrer_id,referee_id,payment_stars,commission_pct,credits_earned,stars_earned) VALUES (?,?,?,?,?,?)", (referrer_id, referee_id, payment_stars, pct, credits_earned, stars_earned))
        await db.execute("INSERT INTO transactions (user_id,amount,type,description,balance) VALUES (?,?,'referral',?,?)", (referrer_id, credits_earned, f"Реф. комиссия {pct}%", new))
        await db.commit()
    return {"referrer_id": referrer_id, "credits_earned": credits_earned, "stars_earned": stars_earned, "percent": pct, "level": level}

async def get_ref_stats(uid):
    user = await db_get("SELECT ref_code,ref_level,referrals_count,stars_balance,stars_earned_total FROM users WHERE id=?", (uid,))
    if not user: return {}
    refs = await db_all("SELECT u.full_name,u.username,r.created_at,r.expires_at,COALESCE(SUM(e.stars_earned),0) as earned FROM referrals r JOIN users u ON u.id=r.referee_id LEFT JOIN referral_earnings e ON e.referee_id=r.referee_id WHERE r.referrer_id=? GROUP BY r.referee_id ORDER BY r.created_at DESC LIMIT 20", (uid,))
    row = await db_get("SELECT COALESCE(SUM(stars_earned),0) as s FROM referral_earnings WHERE referrer_id=? AND created_at>datetime('now','-30 days')", (uid,))
    return {"ref_code": user["ref_code"], "level": user["ref_level"] or "user", "referrals_count": user["referrals_count"] or 0, "stars_balance": user["stars_balance"] or 0, "stars_earned_total": user["stars_earned_total"] or 0, "earned_30d": row["s"] if row else 0, "referrals": refs}

async def request_withdrawal(uid, amount):
    row = await db_get("SELECT stars_balance FROM users WHERE id=?", (uid,))
    bal = row["stars_balance"] if row else 0
    if bal < MIN_WITHDRAW_STARS: return {"ok": False, "error": f"Минимум {MIN_WITHDRAW_STARS} Stars"}
    if amount > bal: return {"ok": False, "error": "Недостаточно Stars"}
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET stars_balance=stars_balance-? WHERE id=?", (amount, uid))
        await db.execute("INSERT INTO withdrawal_requests (user_id,stars_amount) VALUES (?,?)", (uid, amount))
        await db.commit()
    return {"ok": True}

async def set_ref_level(uid, level):
    if level not in REFERRAL_LEVELS: return False
    await db_run("UPDATE users SET ref_level=? WHERE id=?", (level, uid)); return True

async def get_pending_withdrawals():
    return await db_all("SELECT w.id,w.user_id,w.stars_amount,w.created_at,u.username,u.full_name FROM withdrawal_requests w JOIN users u ON u.id=w.user_id WHERE w.status='pending' ORDER BY w.created_at")

async def approve_withdrawal(req_id, approved):
    if not approved:
        row = await db_get("SELECT user_id,stars_amount FROM withdrawal_requests WHERE id=?", (req_id,))
        if row: await db_run("UPDATE users SET stars_balance=stars_balance+? WHERE id=?", (row["stars_amount"], row["user_id"]))
    await db_run("UPDATE withdrawal_requests SET status=?,processed_at=CURRENT_TIMESTAMP WHERE id=?", ("approved" if approved else "rejected", req_id))

async def admin_stats():
    r1 = await db_get("SELECT COUNT(*) as c FROM users")
    r2 = await db_get("SELECT COUNT(*) as c FROM users WHERE plan!='free'")
    r3 = await db_get("SELECT COUNT(*) as c FROM ai_requests WHERE date(created_at)=date('now')")
    r4 = await db_get("SELECT COALESCE(SUM(stars),0) as s FROM payments WHERE status='completed'")
    return (r1["c"] if r1 else 0, r2["c"] if r2 else 0, r3["c"] if r3 else 0, r4["s"] if r4 else 0)

# ══════════════════════════════════════════════════════
#  AI ФУНКЦИИ
# ══════════════════════════════════════════════════════

async def call_text_ai(prompt: str, system: str, model_id: str, uid: int = 0, use_history: bool = False) -> str:
    model_info = TEXT_MODELS.get(model_id, TEXT_MODELS["claude"])
    provider = model_info["provider"]

    # Построить сообщения с историей
    if use_history and uid:
        history = get_history(uid)
        messages = history + [{"role": "user", "content": prompt}]
    else:
        messages = [{"role": "user", "content": prompt}]

    try:
        if provider == "anthropic" and anthropic_client:
            resp = await asyncio.wait_for(
                anthropic_client.messages.create(
                    model="claude-sonnet-4-20250514", max_tokens=1024,
                    system=system, messages=messages),
                timeout=15
            )
            result = resp.content[0].text
        elif provider == "deepseek" and deepseek_client:
            resp = await asyncio.wait_for(
                deepseek_client.chat.completions.create(
                    model="deepseek-chat", max_tokens=1024,
                    messages=[{"role": "system", "content": system}] + messages),
                timeout=15
            )
            result = resp.choices[0].message.content
        elif provider == "openai" and openai_client:
            resp = await asyncio.wait_for(
                openai_client.chat.completions.create(
                    model="gpt-4o", max_tokens=1024,
                    messages=[{"role": "system", "content": system}] + messages),
                timeout=15
            )
            result = resp.choices[0].message.content
        else:
            return "❌ Модель недоступна. Проверь API ключи."

        # Сохранить в историю
        if use_history and uid:
            add_to_history(uid, "user", prompt)
            add_to_history(uid, "assistant", result)

        return result

    except asyncio.TimeoutError:
        logging.error(f"Text AI timeout [{model_id}]")
        raise Exception("Превышено время ожидания. Попробуй ещё раз.")
    except Exception as e:
        logging.error(f"Text AI error [{model_id}]: {e}")
        raise

import base64

async def generate_image_dalle(prompt: str) -> bytes:
    """DALL-E 3 — b64"""
    if not openai_client:
        raise Exception("OpenAI ключ не настроен")
    resp = await asyncio.wait_for(
        openai_client.images.generate(
            model="dall-e-3", prompt=prompt,
            n=1, size="1024x1024", quality="standard",
            response_format="b64_json"
        ), timeout=30
    )
    return base64.b64decode(resp.data[0].b64_json)

async def generate_image_gpt(prompt: str) -> bytes:
    """GPT Image 2 — b64"""
    if not openai_client:
        raise Exception("OpenAI ключ не настроен")
    resp = await asyncio.wait_for(
        openai_client.images.generate(
            model="gpt-image-1", prompt=prompt,
            n=1, size="1024x1024"
        ), timeout=30
    )
    if resp.data[0].b64_json:
        return base64.b64decode(resp.data[0].b64_json)
    url = resp.data[0].url
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.content

# ── KIE.AI ФУНКЦИИ ────────────────────────────────────

async def aiml_request(endpoint: str, payload: dict) -> dict:
    """Базовый запрос к aimlapi.com"""
    if not AIML_KEY:
        raise Exception("AIML_KEY не настроен")
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"https://api.aimlapi.com/{endpoint}",
            headers={"Authorization": f"Bearer {AIML_KEY}", "Content-Type": "application/json"},
            json=payload
        )
        resp.raise_for_status()
        return resp.json()

async def generate_nano_banana(prompt: str) -> bytes:
    """Nano Banana Pro через aimlapi.com"""
    data = await aiml_request("v1/images/generations", {
        "model": "google/nano-banana-pro",
        "prompt": prompt,
        "aspect_ratio": "1:1",
        "resolution": "1K"
    })
    # Получить URL картинки
    url = ""
    if data.get("images"):
        url = data["images"][0].get("url", "")
    elif data.get("data"):
        url = data["data"][0].get("url", "")
    if not url:
        raise Exception(f"Нет URL в ответе: {list(data.keys())}")
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.content

async def generate_img2img(image_url: str, prompt: str) -> bytes:
    """Редактирование фото через Nano Banana 2 (img2img)"""
    data = await aiml_request("v1/images/generations", {
        "model": "google/nano-banana-2",
        "prompt": prompt,
        "image_urls": [image_url],
        "aspect_ratio": "1:1",
        "resolution": "1K"
    })
    url = ""
    if data.get("images"):
        url = data["images"][0].get("url", "")
    elif data.get("data"):
        url = data["data"][0].get("url", "")
    if not url:
        raise Exception(f"Нет URL в ответе: {list(data.keys())}")
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.content

async def generate_video_kling(prompt: str) -> str:
    """Видео Kling через aimlapi.com"""
    if not AIML_KEY:
        raise Exception("AIML_KEY не настроен")
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.aimlapi.com/v2/generate/video/kling/generation",
            headers={"Authorization": f"Bearer {AIML_KEY}", "Content-Type": "application/json"},
            json={
                "model": "kling-video/v1.6/standard/text-to-video",
                "prompt": prompt,
                "duration": "5",
                "aspect_ratio": "16:9"
            }
        )
        resp.raise_for_status()
        data = resp.json()
        task_id = data.get("id") or data.get("generation_id")
        if not task_id:
            raise Exception(f"Нет task_id: {list(data.keys())}")

        # Polling
        for _ in range(36):
            await asyncio.sleep(5)
            r = await client.get(
                f"https://api.aimlapi.com/v2/generate/video/kling/generation?generation_id={task_id}",
                headers={"Authorization": f"Bearer {AIML_KEY}"}
            )
            result = r.json()
            status = result.get("status", "")
            if status == "completed":
                url = result.get("video", {}).get("url", "")
                if url:
                    return url
                raise Exception("Нет URL видео в ответе")
            elif status in ("failed", "error"):
                raise Exception(f"Kling failed: {result}")
        raise Exception("Таймаут генерации видео (3 мин)")

async def generate_music_suno(prompt: str) -> str:
    """Музыка Suno через aimlapi.com"""
    if not AIML_KEY:
        raise Exception("AIML_KEY не настроен")
    async with httpx.AsyncClient(timeout=120) as client:
        # Создать задачу
        resp = await client.post(
            "https://api.aimlapi.com/v2/generate/audio/suno-ai/clip",
            headers={"Authorization": f"Bearer {AIML_KEY}", "Content-Type": "application/json"},
            json={"prompt": prompt, "make_instrumental": False}
        )
        resp.raise_for_status()
        data = resp.json()
        
        # Если уже готово
        clips = data.get("clips", [])
        if clips and clips[0].get("audio_url"):
            return clips[0]["audio_url"]
        
        # Получить task_id и ждать
        task_id = data.get("id") or (clips[0].get("id") if clips else None)
        if not task_id:
            raise Exception(f"Нет task_id: {list(data.keys())}")
        
        # Polling
        for _ in range(24):
            await asyncio.sleep(5)
            r = await client.get(
                f"https://api.aimlapi.com/v2/generate/audio/suno-ai/clip?clip_id={task_id}",
                headers={"Authorization": f"Bearer {AIML_KEY}"}
            )
            result = r.json()
            clips = result.get("clips", [result] if result.get("audio_url") else [])
            if clips and clips[0].get("audio_url"):
                return clips[0]["audio_url"]
            status = result.get("status", "")
            if status in ("failed", "error"):
                raise Exception(f"Suno failed: {result}")
        
        raise Exception("Таймаут генерации музыки")

# ══════════════════════════════════════════════════════
#  КЛАВИАТУРЫ — REPLY KEYBOARD (кнопки внизу)
# ══════════════════════════════════════════════════════

def main_kb() -> ReplyKeyboardMarkup:
    """Главное меню — кнопки внизу экрана как в Syntx AI"""
    b = ReplyKeyboardBuilder()
    b.row(KeyboardButton(text="💡 GPTs/Claude/Gemini"))
    b.row(
        KeyboardButton(text="🎨 Дизайн с ИИ"),
        KeyboardButton(text="🎙 Аудио с ИИ"),
    )
    b.row(
        KeyboardButton(text="🎬 Видео будущего"),
        KeyboardButton(text="🗂 Хранитель изображений"),
    )
    b.row(
        KeyboardButton(text="👤 Профиль"),
        KeyboardButton(text="🔗 Рефералы"),
    )
    b.row(
        KeyboardButton(text="❓ Помощь"),
        KeyboardButton(text="📕 База знаний"),
    )
    return b.as_markup(resize_keyboard=True)

def text_tools_kb() -> ReplyKeyboardMarkup:
    """Меню текстовых инструментов"""
    b = ReplyKeyboardBuilder()
    b.row(KeyboardButton(text="💬 AI Чат"))
    b.row(
        KeyboardButton(text="✍️ Копирайтер"),
        KeyboardButton(text="💻 Код"),
    )
    b.row(
        KeyboardButton(text="🔍 SEO"),
        KeyboardButton(text="🌐 Перевод"),
    )
    b.row(
        KeyboardButton(text="📝 Саммари"),
        KeyboardButton(text="📧 Email"),
    )
    b.row(
        KeyboardButton(text="📄 Эссе"),
        KeyboardButton(text="✏️ Рерайт"),
    )
    b.row(KeyboardButton(text="💡 Идеи"))
    b.row(KeyboardButton(text="🗑 Очистить историю чата"))
    b.row(KeyboardButton(text="🏠 В главное меню"))
    return b.as_markup(resize_keyboard=True)

def design_kb() -> ReplyKeyboardMarkup:
    """Меню дизайна"""
    b = ReplyKeyboardBuilder()
    b.row(KeyboardButton(text="🍌 Nano Banana"))
    b.row(KeyboardButton(text="🖼 GPT Image 2"))
    b.row(KeyboardButton(text="🎨 DALL-E 3"))
    b.row(KeyboardButton(text="✏️ Редактировать фото"))
    b.row(KeyboardButton(text="🏠 В главное меню"))
    return b.as_markup(resize_keyboard=True)

def model_kb() -> ReplyKeyboardMarkup:
    """Выбор модели"""
    b = ReplyKeyboardBuilder()
    b.row(KeyboardButton(text="🅰 Claude Sonnet — 10 кр."))
    b.row(KeyboardButton(text="🐋 DeepSeek V3 — 5 кр."))
    b.row(KeyboardButton(text="✳️ GPT-4o — 15 кр."))
    b.row(KeyboardButton(text="🏠 В главное меню"))
    return b.as_markup(resize_keyboard=True)

def cancel_kb() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.row(KeyboardButton(text="❌ Отмена"))
    return b.as_markup(resize_keyboard=True)

def profile_kb() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.row(
        KeyboardButton(text="💎 Купить кредиты"),
        KeyboardButton(text="👑 Подписки"),
    )
    b.row(KeyboardButton(text="📋 История транзакций"))
    b.row(KeyboardButton(text="🏠 В главное меню"))
    return b.as_markup(resize_keyboard=True)

def credits_pack_kb():
    b = InlineKeyboardBuilder()
    for pid, pack in CREDIT_PACKS.items():
        b.row(InlineKeyboardButton(text=f"{pack['name']}  ·  ⭐️ {pack['stars']}", callback_data=f"buy_credits_{pid}"))
    return b.as_markup()

def plans_inline_kb():
    b = InlineKeyboardBuilder()
    for pid, p in PLANS.items():
        b.row(InlineKeyboardButton(text=f"{p['emoji']} {p['name']}  ·  ⭐️ {p['stars']}/мес", callback_data=f"buy_plan_{pid}"))
    return b.as_markup()

def ref_inline_kb():
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="📊 Статистика", callback_data="ref_stats"),
        InlineKeyboardButton(text="👥 Рефералы",   callback_data="ref_list"),
    )
    b.row(
        InlineKeyboardButton(text="⭐️ Вывести Stars", callback_data="ref_withdraw"),
        InlineKeyboardButton(text="❓ Как работает",  callback_data="ref_howto"),
    )
    return b.as_markup()

# ══════════════════════════════════════════════════════
#  РОУТЕР И FSM
# ══════════════════════════════════════════════════════

router = Router()

class State_(StatesGroup):
    # Текстовые инструменты
    choose_model  = State()
    waiting_text  = State()
    # Картинки
    waiting_image = State()
    # Редактирование фото
    waiting_photo      = State()
    waiting_photo_text = State()

user_tool:  dict[int, str] = {}
user_model: dict[int, str] = {}
user_image_model: dict[int, str] = {}
# История чатов — последние 10 сообщений на пользователя
chat_history: dict[int, list] = {}

def get_history(uid: int) -> list:
    return chat_history.get(uid, [])

def add_to_history(uid: int, role: str, content: str):
    if uid not in chat_history:
        chat_history[uid] = []
    chat_history[uid].append({"role": role, "content": content})
    # Держать только последние 30 сообщений
    if len(chat_history[uid]) > 30:
        chat_history[uid] = chat_history[uid][-30:]

def clear_history(uid: int):
    chat_history[uid] = []

TOOL_MAP = {
    "💬 AI Чат":     ("chat",      10),
    "✍️ Копирайтер": ("copywriter",20),
    "💻 Код":        ("code",       25),
    "🔍 SEO":        ("seo",        35),
    "🌐 Перевод":    ("translate",  15),
    "📝 Саммари":    ("summarize",  15),
    "📧 Email":      ("email",      20),
    "📄 Эссе":       ("essay",      25),
    "✏️ Рерайт":     ("rewrite",    20),
    "💡 Идеи":       ("idea",       15),
}

MODEL_MAP = {
    "🅰 Claude Sonnet — 10 кр.": "claude",
    "🐋 DeepSeek V3 — 5 кр.":   "deepseek",
    "✳️ GPT-4o — 15 кр.":       "gpt4o",
}

TOOL_HINTS = {
    "chat":       "Задай любой вопрос:",
    "copywriter": "Опиши что нужно написать (лэндинг, пост, реклама):",
    "code":       "Опиши задачу или вставь код для анализа:",
    "seo":        "Введи тему для SEO-анализа:",
    "translate":  "Вставь текст для перевода (укажи язык):",
    "summarize":  "Вставь текст для краткого пересказа:",
    "email":      "Опиши задачу для письма:",
    "essay":      "Введи тему для эссе или статьи:",
    "rewrite":    "Вставь текст для рерайта:",
    "idea":       "Опиши задачу — получи идеи:",
}

# ══════════════════════════════════════════════════════
#  /start
# ══════════════════════════════════════════════════════

@router.message(CommandStart())
async def cmd_start(message: Message):
    args = message.text.split()
    ref_code = args[1].replace("ref_", "") if len(args) > 1 and args[1].startswith("ref_") else None
    user = await get_user(message.from_user.id)

    if not user:
        await create_user(message.from_user.id, message.from_user.username or "", message.from_user.full_name or "")
        if ref_code:
            referrer = await get_user_by_ref_code(ref_code)
            if referrer and referrer["id"] != message.from_user.id:
                ok = await register_referral(referrer["id"], message.from_user.id)
                if ok:
                    await add_credits(message.from_user.id, REFERRAL_BONUS, "bonus", "Бонус за реф-ссылку")
                    try: await message.bot.send_message(referrer["id"], "🎉 По твоей ссылке зарегистрировался новый пользователь!")
                    except: pass
        bal = await get_balance(message.from_user.id)
        text = f"✨ *Добро пожаловать в AuraAI!*\n\n🎁 Тебе начислено *{bal} кредитов* для старта\n\nВыбери раздел:"
    else:
        bal = await get_balance(message.from_user.id)
        text = f"👋 С возвращением, *{message.from_user.first_name}*!\n\n💎 Кредиты: *{bal}*\n\nВыбери раздел:"

    await message.answer(text, parse_mode="Markdown", reply_markup=main_kb())

# ══════════════════════════════════════════════════════
#  ГЛАВНЫЕ РАЗДЕЛЫ
# ══════════════════════════════════════════════════════

@router.message(F.text == "🏠 В главное меню")
async def to_main(message: Message, state: FSMContext):
    await state.clear()
    bal = await get_balance(message.from_user.id)
    await message.answer(f"🏠 *Главное меню*\n\n💎 Кредиты: *{bal}*", parse_mode="Markdown", reply_markup=main_kb())

@router.message(F.text == "❌ Отмена")
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено.", reply_markup=main_kb())

@router.message(F.text == "🗑 Очистить историю чата")
async def clear_chat_history(message: Message):
    clear_history(message.from_user.id)
    await message.answer("🗑 История чата очищена!", reply_markup=text_tools_kb())

@router.message(F.text == "💡 GPTs/Claude/Gemini")
async def section_text(message: Message):
    await message.answer(
        "💡 *GPTs / Claude / Gemini*\n\nВыбери инструмент:",
        parse_mode="Markdown", reply_markup=text_tools_kb()
    )

@router.message(F.text == "🎨 Дизайн с ИИ")
async def section_design(message: Message):
    await message.answer(
        "🎨 *Дизайн с ИИ*\n\nГенерация изображений по описанию:",
        parse_mode="Markdown", reply_markup=design_kb()
    )

def audio_kb() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.row(KeyboardButton(text="🎵 Сгенерировать музыку"))
    b.row(KeyboardButton(text="🏠 В главное меню"))
    return b.as_markup(resize_keyboard=True)

@router.message(F.text == "🎙 Аудио с ИИ")
async def section_audio(message: Message):
    await message.answer(
        "🎙 *Аудио с ИИ*\n\n🎵 Suno v4 — генерация музыки по описанию\n💎 50 кредитов за трек",
        parse_mode="Markdown", reply_markup=audio_kb()
    )

def video_kb() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.row(KeyboardButton(text="🎬 Создать видео Kling"))
    b.row(KeyboardButton(text="🏠 В главное меню"))
    return b.as_markup(resize_keyboard=True)

@router.message(F.text == "🎬 Видео будущего")
async def section_video(message: Message):
    await message.answer(
        "🎬 *Видео будущего*\n\n🎬 Kling 3.0 — видео из текста до 5 сек\n💎 150 кредитов за видео",
        parse_mode="Markdown", reply_markup=video_kb()
    )

@router.message(F.text == "🗂 Хранитель изображений")
async def section_storage(message: Message):
    await message.answer(
        "🗂 *Хранитель изображений*\n\n⏳ Раздел в разработке.\n\nСкоро: хранение и организация всех сгенерированных картинок.",
        parse_mode="Markdown", reply_markup=main_kb()
    )

@router.message(F.text == "📕 База знаний")
async def section_knowledge(message: Message):
    await message.answer(
        "📕 *База знаний*\n\n⏳ Раздел в разработке.\n\nСкоро: обучающие материалы по работе с AI.",
        parse_mode="Markdown", reply_markup=main_kb()
    )

@router.message(F.text == "❓ Помощь")
async def section_help(message: Message):
    await message.answer(
        "❓ *Помощь*\n\n"
        "💡 *GPTs/Claude/Gemini* — текстовые AI инструменты\n"
        "🎨 *Дизайн с ИИ* — генерация картинок\n"
        "🎙 *Аудио с ИИ* — музыка и голос (скоро)\n"
        "🎬 *Видео будущего* — AI видео (скоро)\n\n"
        "💎 Кредиты списываются за каждый запрос\n"
        "🔗 Рефералы — приглашай и зарабатывай Stars\n\n"
        "🆘 Поддержка: @support",
        parse_mode="Markdown", reply_markup=main_kb()
    )

# ══════════════════════════════════════════════════════
#  ПРОФИЛЬ
# ══════════════════════════════════════════════════════

@router.message(F.text == "👤 Профиль")
async def section_profile(message: Message):
    user = await get_user(message.from_user.id)
    bal  = await get_balance(message.from_user.id)
    plan_label = {"free": "Free", "pro": "👑 Pro", "team": "💎 Team"}.get(user["plan"] if user else "free", "Free")
    expires = ""
    if user and user["plan_expires"]:
        expires = f"\n📅 До: *{user['plan_expires'][:10]}*"

    await message.answer(
        f"👤 *Профиль*\n\n"
        f"Имя: *{message.from_user.full_name}*\n"
        f"Plan: *{plan_label}*{expires}\n"
        f"💎 Кредиты: *{bal}*\n"
        f"🏅 Всего начислено: *{user['credits_total'] if user else 0}*",
        parse_mode="Markdown", reply_markup=profile_kb()
    )

@router.message(F.text == "💎 Купить кредиты")
async def buy_credits(message: Message):
    await message.answer(
        "⭐️ *Купить кредиты за Telegram Stars*\n\nКредиты зачисляются мгновенно и не сгорают.",
        parse_mode="Markdown", reply_markup=credits_pack_kb()
    )

@router.message(F.text == "👑 Подписки")
async def buy_plans(message: Message):
    user = await get_user(message.from_user.id)
    plan = user["plan"] if user else "free"
    lines = ["👑 *Подписки AuraAI*\n"]
    for pid, p in PLANS.items():
        active = "✅ " if plan == pid else ""
        lines.append(f"{active}*{p['emoji']} {p['name']}* — ⭐️ {p['stars']}/мес\n  {p['description']}\n")
    await message.answer("\n".join(lines), parse_mode="Markdown", reply_markup=plans_inline_kb())

@router.message(F.text == "📋 История транзакций")
async def tx_history(message: Message):
    rows = await db_all("SELECT amount,description,balance,created_at FROM transactions WHERE user_id=? ORDER BY created_at DESC LIMIT 10", (message.from_user.id,))
    bal = await get_balance(message.from_user.id)
    lines = [f"📋 *История*\n\nБаланс: *{bal} кр.*\n"]
    for r in rows:
        sign = "+" if r["amount"] > 0 else ""
        lines.append(f"`{r['created_at'][:10]}` {sign}{r['amount']} — {r['description']}")
    if not rows: lines.append("История пуста")
    await message.answer("\n".join(lines), parse_mode="Markdown", reply_markup=profile_kb())

# ══════════════════════════════════════════════════════
#  ТЕКСТОВЫЕ ИНСТРУМЕНТЫ — ВЫБОР МОДЕЛИ
# ══════════════════════════════════════════════════════

@router.message(lambda m: m.text in TOOL_MAP)
async def tool_selected(message: Message, state: FSMContext):
    tool_id, base_cost = TOOL_MAP[message.text]
    bal = await get_balance(message.from_user.id)

    if bal < base_cost:
        await message.answer(f"❌ Нужно минимум *{base_cost} кр.* · У тебя *{bal} кр.*\n\nПополни баланс:", parse_mode="Markdown", reply_markup=profile_kb())
        return

    user_tool[message.from_user.id] = tool_id
    await state.set_state(State_.choose_model)
    await message.answer(
        f"*{message.text}*\n\nВыбери AI модель:",
        parse_mode="Markdown", reply_markup=model_kb()
    )

@router.message(State_.choose_model, lambda m: m.text in MODEL_MAP)
async def model_selected(message: Message, state: FSMContext):
    model_id = MODEL_MAP[message.text]
    tool_id  = user_tool.get(message.from_user.id, "chat")
    base_cost = TOOL_MAP.get(next((k for k, v in TOOL_MAP.items() if v[0] == tool_id), "💬 AI Чат"), ("chat", 10))[1]
    model_cost = TEXT_MODELS[model_id]["cost"]
    total_cost = base_cost + model_cost

    bal = await get_balance(message.from_user.id)
    if bal < total_cost:
        await message.answer(f"❌ Нужно *{total_cost} кр.* · У тебя *{bal} кр.*", parse_mode="Markdown", reply_markup=profile_kb())
        await state.clear(); return

    user_model[message.from_user.id] = model_id
    await state.update_data(tool=tool_id, model=model_id, cost=total_cost)
    await state.set_state(State_.waiting_text)

    model_info = TEXT_MODELS[model_id]
    hint = TOOL_HINTS.get(tool_id, "Введи запрос:")
    await message.answer(
        f"{model_info['emoji']} *{model_info['name']}*  ·  💎 {total_cost} кредитов\n\n{hint}",
        parse_mode="Markdown", reply_markup=cancel_kb()
    )

@router.message(State_.choose_model, F.text == "🏠 В главное меню")
async def model_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🏠 Главное меню", reply_markup=main_kb())

@router.message(State_.waiting_text)
async def process_text(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=main_kb()); return

    data = await state.get_data()
    tool_id  = data.get("tool", "chat")
    model_id = data.get("model", "claude")
    cost     = data.get("cost", 10)

    ok = await use_credits(message.from_user.id, tool_id, cost)
    if not ok:
        await message.answer("❌ Недостаточно кредитов.", reply_markup=profile_kb())
        await state.clear(); return

    await state.clear()
    thinking = await message.answer("⏳ Генерирую...", reply_markup=ReplyKeyboardRemove())

    try:
        system = SYSTEM_PROMPTS.get(tool_id, SYSTEM_PROMPTS["chat"])
        use_history = (tool_id == "chat")
        result = await call_text_ai(message.text, system, model_id, uid=message.from_user.id, use_history=use_history)
        bal    = await get_balance(message.from_user.id)
        model_info = TEXT_MODELS.get(model_id, TEXT_MODELS["claude"])

        await log_request(message.from_user.id, tool_id, model_id, cost)

        chunks = [result[i:i+3500] for i in range(0, len(result), 3500)]
        for i, chunk in enumerate(chunks):
            if i == 0:
                try:
                    await thinking.edit_text(
                        f"{model_info['emoji']} *{model_info['name']}*\n\n{chunk}\n\n"
                        f"💎 Потрачено: *{cost} кр.* · Остаток: *{bal} кр.*",
                        parse_mode="Markdown"
                    )
                except Exception:
                    await message.answer(
                        f"{model_info['emoji']} *{model_info['name']}*\n\n{chunk}\n\n"
                        f"💎 Потрачено: *{cost} кр.* · Остаток: *{bal} кр.*",
                        parse_mode="Markdown"
                    )
            else:
                await message.answer(chunk)

        await message.answer("Что дальше?", reply_markup=text_tools_kb())

    except asyncio.TimeoutError:
        await add_credits(message.from_user.id, cost, "bonus", "Возврат: таймаут")
        try:
            await thinking.edit_text("⏱ Время вышло (15 сек). Кредиты возвращены. Попробуй ещё раз.")
        except Exception:
            await message.answer("⏱ Время вышло (15 сек). Кредиты возвращены. Попробуй ещё раз.")
        await message.answer("Выбери инструмент:", reply_markup=text_tools_kb())
        logging.error(f"Text AI timeout [{tool_id}/{model_id}]")

    except Exception as e:
        await add_credits(message.from_user.id, cost, "bonus", "Возврат: ошибка AI")
        try:
            await thinking.edit_text(f"⚠️ Ошибка AI. Кредиты возвращены.\n\n{str(e)[:100]}")
        except Exception:
            await message.answer(f"⚠️ Ошибка AI. Кредиты возвращены.")
        await message.answer("Попробуй ещё раз:", reply_markup=text_tools_kb())
        logging.error(f"Text AI error [{tool_id}/{model_id}]: {e}")

# ══════════════════════════════════════════════════════
#  ГЕНЕРАЦИЯ КАРТИНОК
# ══════════════════════════════════════════════════════

@router.message(F.text.in_({"🖼 GPT Image 2", "🎨 DALL-E 3", "🍌 Nano Banana"}))
async def image_tool_selected(message: Message, state: FSMContext):
    if "Nano Banana" in message.text:
        cost = 60
    elif "GPT Image 2" in message.text:
        cost = 80
    else:
        cost = 50
    bal  = await get_balance(message.from_user.id)

    if bal < cost:
        await message.answer(f"❌ Нужно *{cost} кр.* · У тебя *{bal} кр.*", parse_mode="Markdown", reply_markup=profile_kb())
        return

    if "Nano Banana" in message.text:
        model = "nano"
    elif "GPT Image 2" in message.text:
        model = "gpt"
    else:
        model = "dalle"
    user_image_model[message.from_user.id] = model
    await state.set_state(State_.waiting_image)
    await state.update_data(image_model=model, cost=cost)

    await message.answer(
        f"*{message.text}*  ·  💎 {cost} кредитов\n\n"
        f"Опиши картинку которую хочешь создать:\n\n"
        f"Пример: *красивый закат над горами, фотореализм, 4K*",
        parse_mode="Markdown", reply_markup=cancel_kb()
    )

@router.message(State_.waiting_image)
async def process_image(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=design_kb()); return

    data  = await state.get_data()
    model = data.get("image_model", "dalle")
    cost  = data.get("cost", 50)

    ok = await use_credits(message.from_user.id, f"image_{model}", cost)
    if not ok:
        await message.answer("❌ Недостаточно кредитов.", reply_markup=profile_kb())
        await state.clear(); return

    await state.clear()
    thinking = await message.answer("🎨 Генерирую картинку... (~15-30 сек)", reply_markup=ReplyKeyboardRemove())

    try:
        bal = await get_balance(message.from_user.id)

        if model == "music":
            try:
                await thinking.edit_text("🎵 Генерирую музыку... (~30-60 сек)")
            except Exception:
                pass
            url = await generate_music_suno(message.text)
            try:
                await thinking.delete()
            except Exception:
                pass
            await message.answer_audio(
                url,
                caption=f"🎵 *Suno v4*\n\n💎 Потрачено: *{cost} кр.* · Остаток: *{bal} кр.*",
                parse_mode="Markdown"
            )
            await message.answer("Что дальше?", reply_markup=audio_kb())

        elif model == "video":
            try:
                await thinking.edit_text("🎬 Генерирую видео... (~60-180 сек)")
            except Exception:
                pass
            url = await generate_video_kling(message.text)
            try:
                await thinking.delete()
            except Exception:
                pass
            await message.answer_video(
                url,
                caption=f"🎬 *Kling 3.0*\n\n💎 Потрачено: *{cost} кр.* · Остаток: *{bal} кр.*",
                parse_mode="Markdown"
            )
            await message.answer("Что дальше?", reply_markup=video_kb())

        else:
            if model == "nano":
                img_bytes = await generate_nano_banana(message.text)
            elif model == "gpt":
                img_bytes = await generate_image_gpt(message.text)
            else:
                img_bytes = await generate_image_dalle(message.text)

            model_name = {"nano": "🍌 Nano Banana", "gpt": "GPT Image 2", "dalle": "DALL-E 3"}.get(model, model)
            try:
                await thinking.delete()
            except Exception:
                pass
            await message.answer_photo(
                BufferedInputFile(img_bytes, filename="image.png"),
                caption=f"🎨 *{model_name}*\n\n💎 Потрачено: *{cost} кр.* · Остаток: *{bal} кр.*",
                parse_mode="Markdown"
            )
            await message.answer("Что дальше?", reply_markup=design_kb())

        await log_request(message.from_user.id, f"media_{model}", model, cost)

    except asyncio.TimeoutError:
        await add_credits(message.from_user.id, cost, "bonus", "Возврат: таймаут")
        await message.answer("⏱ Время вышло. Кредиты возвращены.")
        kb = audio_kb() if model == "music" else (video_kb() if model == "video" else design_kb())
        await message.answer("Попробуй снова:", reply_markup=kb)

    except Exception as e:
        await add_credits(message.from_user.id, cost, "bonus", "Возврат: ошибка")
        await message.answer(f"⚠️ Ошибка. Кредиты возвращены.
{str(e)[:150]}")
        kb = audio_kb() if model == "music" else (video_kb() if model == "video" else design_kb())
        await message.answer("Попробуй снова:", reply_markup=kb)
        logging.error(f"Media generation error [{model}]: {e}")

# ══════════════════════════════════════════════════════
#  РЕФЕРАЛЫ
# ══════════════════════════════════════════════════════

@router.message(F.text == "🎵 Сгенерировать музыку")
async def music_generate(message: Message, state: FSMContext):
    cost = 50
    bal  = await get_balance(message.from_user.id)
    if bal < cost:
        await message.answer(f"❌ Нужно *{cost} кр.* · У тебя *{bal} кр.*", parse_mode="Markdown", reply_markup=profile_kb())
        return
    await state.set_state(State_.waiting_image)
    await state.update_data(image_model="music", cost=cost)
    await message.answer(
        f"🎵 *Suno v4*  ·  💎 {cost} кредитов\n\n"
        f"Опиши музыку которую хочешь создать:\n\n"
        f"Пример: *энергичный рок трек для мотивации, гитара и барабаны*",
        parse_mode="Markdown", reply_markup=cancel_kb()
    )

@router.message(F.text == "🎬 Создать видео Kling")
async def video_generate(message: Message, state: FSMContext):
    cost = 150
    bal  = await get_balance(message.from_user.id)
    if bal < cost:
        await message.answer(f"❌ Нужно *{cost} кр.* · У тебя *{bal} кр.*", parse_mode="Markdown", reply_markup=profile_kb())
        return
    await state.set_state(State_.waiting_image)
    await state.update_data(image_model="video", cost=cost)
    await message.answer(
        f"🎬 *Kling 3.0*  ·  💎 {cost} кредитов\n\n"
        f"Опиши видео которое хочешь создать:\n\n"
        f"Пример: *закат над морем, волны, кинематографичная съёмка*",
        parse_mode="Markdown", reply_markup=cancel_kb()
    )

# ── РЕДАКТИРОВАНИЕ ФОТО ───────────────────────────────

user_photo_urls: dict[int, str] = {}

@router.message(F.text == "✏️ Редактировать фото")
async def img2img_start(message: Message, state: FSMContext):
    cost = 70
    bal = await get_balance(message.from_user.id)
    if bal < cost:
        await message.answer(f"❌ Нужно *{cost} кр.* · У тебя *{bal} кр.*", parse_mode="Markdown", reply_markup=profile_kb())
        return
    await state.set_state(State_.waiting_photo)
    await state.update_data(cost=cost)
    await message.answer(
        "✏️ *Редактировать фото*  ·  💎 70 кредитов

"
        "1️⃣ Отправь фото которое хочешь изменить:",
        parse_mode="Markdown", reply_markup=cancel_kb()
    )

@router.message(State_.waiting_photo, F.photo)
async def img2img_photo_received(message: Message, state: FSMContext):
    # Получить наибольшее фото
    photo = message.photo[-1]
    file = await message.bot.get_file(photo.file_id)
    file_url = f"https://api.telegram.org/file/bot{message.bot.token}/{file.file_path}"
    user_photo_urls[message.from_user.id] = file_url
    await state.set_state(State_.waiting_photo_text)
    await message.answer(
        "✅ Фото получено!

"
        "2️⃣ Теперь опиши что хочешь изменить:

"
        "Примеры:
"
        "• *сделай фон розовым*
"
        "• *добавь снег*
"
        "• *измени стиль на аниме*
"
        "• *убери фон*",
        parse_mode="Markdown", reply_markup=cancel_kb()
    )

@router.message(State_.waiting_photo, F.text != "❌ Отмена")
async def img2img_no_photo(message: Message):
    await message.answer("📸 Пожалуйста отправь фото (не файл, а именно фото):")

@router.message(State_.waiting_photo_text)
async def img2img_process(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=design_kb())
        return

    data = await state.get_data()
    cost = data.get("cost", 70)
    image_url = user_photo_urls.get(message.from_user.id)

    if not image_url:
        await message.answer("❌ Фото не найдено. Начни заново.", reply_markup=design_kb())
        await state.clear()
        return

    ok = await use_credits(message.from_user.id, "img2img", cost)
    if not ok:
        await message.answer("❌ Недостаточно кредитов.", reply_markup=profile_kb())
        await state.clear()
        return

    await state.clear()
    thinking = await message.answer("✏️ Редактирую фото... (~15-30 сек)", reply_markup=ReplyKeyboardRemove())

    try:
        img_bytes = await generate_img2img(image_url, message.text)
        bal = await get_balance(message.from_user.id)
        await thinking.delete()
        await message.answer_photo(
            BufferedInputFile(img_bytes, filename="edited.png"),
            caption=f"✏️ *Редактирование фото*

💎 Потрачено: *{cost} кр.* · Остаток: *{bal} кр.*",
            parse_mode="Markdown"
        )
        await message.answer("Что дальше?", reply_markup=design_kb())
        await log_request(message.from_user.id, "img2img", "nano-banana-2", cost)

    except asyncio.TimeoutError:
        await add_credits(message.from_user.id, cost, "bonus", "Возврат: таймаут")
        try:
            await thinking.edit_text("⏱ Время вышло. Кредиты возвращены.")
        except Exception:
            await message.answer("⏱ Время вышло. Кредиты возвращены.")
        await message.answer("Попробуй снова:", reply_markup=design_kb())

    except Exception as e:
        await add_credits(message.from_user.id, cost, "bonus", "Возврат: ошибка")
        try:
            await thinking.edit_text(f"⚠️ Ошибка. Кредиты возвращены.
{str(e)[:100]}")
        except Exception:
            await message.answer("⚠️ Ошибка. Кредиты возвращены.")
        await message.answer("Попробуй снова:", reply_markup=design_kb())
        logging.error(f"img2img error: {e}")

@router.message(F.text == "🔗 Рефералы")
async def section_referral(message: Message):
    ref_code = await get_or_create_ref_code(message.from_user.id)
    stats    = await get_ref_stats(message.from_user.id)
    info     = REFERRAL_LEVELS[stats.get("level", "user")]
    link     = f"https://t.me/{BOT_USERNAME}?start=ref_{ref_code}"
    await message.answer(
        f"🔗 *Реферальная программа*\n\n"
        f"{info['emoji']} *{info['name']}* — *{info['percent']}%*\n\n"
        f"👥 Рефералов: *{stats.get('referrals_count', 0)}*\n"
        f"⭐️ Stars на балансе: *{stats.get('stars_balance', 0)}*\n"
        f"📈 За 30 дней: *{stats.get('earned_30d', 0)} Stars*\n"
        f"🏆 Всего: *{stats.get('stars_earned_total', 0)} Stars*\n\n"
        f"🔗 Твоя ссылка:\n`{link}`",
        parse_mode="Markdown", reply_markup=main_kb()
    )
    await message.answer("Выбери действие:", reply_markup=ref_inline_kb())

@router.callback_query(F.data == "ref_stats")
async def cb_ref_stats(callback: CallbackQuery):
    stats = await get_ref_stats(callback.from_user.id)
    info  = REFERRAL_LEVELS[stats.get("level", "user")]
    levels = list(REFERRAL_LEVELS.keys())
    idx = levels.index(stats.get("level", "user"))
    tip = ""
    if idx < len(levels)-1:
        nxt = levels[idx+1]
        tip = f"\n\n📈 До *{REFERRAL_LEVELS[nxt]['name']}*: ещё *{max(0, PARTNER_MIN_REFS - stats.get('referrals_count',0))} рефералов*" if nxt == "partner" else "\n\n🌟 До Блогера: обратись к администратору"
    await callback.message.answer(
        f"📊 *Статистика рефералов*\n\n"
        f"{info['emoji']} *{info['name']}* — {info['percent']}%\n"
        f"👥 Рефералов: *{stats.get('referrals_count',0)}*\n"
        f"⭐️ На балансе: *{stats.get('stars_balance',0)}*\n"
        f"🏆 Всего: *{stats.get('stars_earned_total',0)}*{tip}",
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "ref_list")
async def cb_ref_list(callback: CallbackQuery):
    stats = await get_ref_stats(callback.from_user.id)
    refs  = stats.get("referrals", [])
    if not refs:
        text = "👥 Рефералов пока нет.\nПоделись ссылкой!"
    else:
        lines = [f"👥 *Рефералы* ({len(refs)})\n"]
        for r in refs:
            name = r["full_name"] or r["username"] or "Аноним"
            lines.append(f"• *{name}* — ⭐️ {r['earned'] or 0} Stars")
        text = "\n".join(lines)
    await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer()

@router.callback_query(F.data == "ref_withdraw")
async def cb_ref_withdraw(callback: CallbackQuery):
    stats = await get_ref_stats(callback.from_user.id)
    bal   = stats.get("stars_balance", 0)
    b     = InlineKeyboardBuilder()
    text  = f"⭐️ *Вывод Stars*\n\nБаланс: *{bal}*\nМинимум: *{MIN_WITHDRAW_STARS}*\n\n"
    if bal >= MIN_WITHDRAW_STARS:
        text += "Выбери сумму:"
        seen = set()
        for a in [100, 500, 1000, bal]:
            if a <= bal and a not in seen:
                seen.add(a)
                b.row(InlineKeyboardButton(text=f"⭐️ {a}", callback_data=f"withdraw_{a}"))
    else:
        text += f"Нужно ещё *{MIN_WITHDRAW_STARS - bal} Stars*"
    await callback.message.answer(text, parse_mode="Markdown", reply_markup=b.as_markup())
    await callback.answer()

@router.callback_query(F.data.startswith("withdraw_"))
async def cb_withdraw(callback: CallbackQuery):
    amount = int(callback.data.split("_")[1])
    result = await request_withdrawal(callback.from_user.id, amount)
    text = f"✅ Заявка на *{amount} Stars* создана. Обработка до 24 ч." if result["ok"] else f"❌ {result['error']}"
    await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer()

@router.callback_query(F.data == "ref_howto")
async def cb_ref_howto(callback: CallbackQuery):
    await callback.message.answer(
        "❓ *Реферальная программа*\n\n"
        "👤 Пользователь — *10%*\n"
        "🤝 Партнёр — *25%* (10+ рефералов)\n"
        "🌟 Блогер — *50%* (по запросу)\n\n"
        "📅 Срок: 12 месяцев\n"
        "⭐️ Вывод Stars от 100\n\n"
        "📈 Пример блогера:\n100 чел × 500 Stars × 50% = *25 000 Stars/мес* 🔥",
        parse_mode="Markdown"
    )
    await callback.answer()

# ══════════════════════════════════════════════════════
#  ОПЛАТА
# ══════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("buy_credits_"))
async def cb_invoice_credits(callback: CallbackQuery):
    pack = CREDIT_PACKS.get(callback.data.replace("buy_credits_", ""))
    if not pack: return
    await callback.bot.send_invoice(
        chat_id=callback.from_user.id,
        title=f"AuraAI — {pack['name']}",
        description=f"Пополнение: {pack['credits']} кредитов",
        payload=f"credits_{callback.data.replace('buy_credits_', '')}",
        currency="XTR",
        prices=[LabeledPrice(label=pack["name"], amount=pack["stars"])],
    )
    await callback.answer()

@router.callback_query(F.data.startswith("buy_plan_"))
async def cb_invoice_plan(callback: CallbackQuery):
    plan = PLANS.get(callback.data.replace("buy_plan_", ""))
    if not plan: return
    await callback.bot.send_invoice(
        chat_id=callback.from_user.id,
        title=f"AuraAI {plan['name']} — 30 дней",
        description=plan["description"],
        payload=f"plan_{callback.data.replace('buy_plan_', '')}",
        currency="XTR",
        prices=[LabeledPrice(label=f"AuraAI {plan['name']}", amount=plan["stars"])],
    )
    await callback.answer()

@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery): await query.answer(ok=True)

@router.message(F.successful_payment)
async def on_payment(message: Message):
    payload = message.successful_payment.invoice_payload
    stars   = message.successful_payment.total_amount
    uid     = message.from_user.id

    if payload.startswith("credits_"):
        pack = CREDIT_PACKS.get(payload.replace("credits_", ""))
        if pack:
            new_bal = await add_credits(uid, pack["credits"], "purchase", f"Покупка: {pack['name']}")
            await message.answer(f"✅ *Оплата прошла!*\n\n💎 +{pack['credits']} кредитов\n💰 Баланс: *{new_bal} кр.*", parse_mode="Markdown", reply_markup=main_kb())
    elif payload.startswith("plan_"):
        plan = PLANS.get(payload.replace("plan_", ""))
        if plan:
            await set_plan(uid, payload.replace("plan_", ""), plan["credits"], plan["days"])
            bal = await get_balance(uid)
            await message.answer(f"✅ *{plan['name']} активирован!*\n\n💎 +{plan['credits']} кредитов\n💰 Баланс: *{bal} кр.*", parse_mode="Markdown", reply_markup=main_kb())

    commission = await process_commission(uid, stars)
    if commission:
        try:
            info = REFERRAL_LEVELS[commission["level"]]
            await message.bot.send_message(commission["referrer_id"],
                f"💰 *Реферальная комиссия!*\n\n{info['emoji']} {info['name']} ({commission['percent']}%)\nНачислено: *+{commission['credits_earned']} кр.* и ⭐️ *{commission['stars_earned']}*", parse_mode="Markdown")
        except: pass

    await db_run("INSERT INTO payments (user_id,type,product_id,stars) VALUES (?,?,?,?)", (uid, "purchase", payload, stars))

# ══════════════════════════════════════════════════════
#  АДМИН
# ══════════════════════════════════════════════════════

@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id != ADMIN_ID: return
    total, paid, today, stars = await admin_stats()
    await message.answer(
        f"🔐 *Админ AuraAI v3*\n\n👥 Всего: *{total}*\n👑 Платных: *{paid}*\n📨 Сегодня: *{today}*\n⭐️ Stars: *{stars}*",
        parse_mode="Markdown"
    )

@router.message(Command("setlevel"))
async def cmd_setlevel(message: Message):
    if message.from_user.id != ADMIN_ID: return
    parts = message.text.split()
    if len(parts) != 3: await message.answer("Формат: /setlevel USER_ID LEVEL"); return
    ok = await set_ref_level(int(parts[1]), parts[2].lower())
    if ok:
        info = REFERRAL_LEVELS[parts[2].lower()]
        await message.answer(f"✅ Уровень *{info['name']}* установлен", parse_mode="Markdown")
        try: await message.bot.send_message(int(parts[1]), f"🎉 Твой уровень повышен до *{info['name']}* — {info['percent']}%!", parse_mode="Markdown")
        except: pass
    else: await message.answer("❌ Неверный уровень")

@router.message(Command("withdrawals"))
async def cmd_withdrawals(message: Message):
    if message.from_user.id != ADMIN_ID: return
    requests = await get_pending_withdrawals()
    if not requests: await message.answer("✅ Заявок нет"); return
    for req in requests:
        name = req["full_name"] or req["username"] or str(req["user_id"])
        b = InlineKeyboardBuilder()
        b.row(
            InlineKeyboardButton(text="✅ Выплатить", callback_data=f"wd_ok_{req['id']}_{req['user_id']}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"wd_no_{req['id']}_{req['user_id']}"),
        )
        await message.answer(f"🔔 *#{req['id']}* · {name}\n⭐️ {req['stars_amount']} Stars", parse_mode="Markdown", reply_markup=b.as_markup())

@router.callback_query(F.data.startswith("wd_ok_"))
async def cb_wd_ok(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    parts = callback.data.split("_")
    await approve_withdrawal(int(parts[2]), True)
    await callback.message.edit_text(f"✅ Заявка #{parts[2]} одобрена")
    try: await callback.bot.send_message(int(parts[3]), "✅ Заявка на вывод Stars одобрена!")
    except: pass

@router.callback_query(F.data.startswith("wd_no_"))
async def cb_wd_no(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    parts = callback.data.split("_")
    await approve_withdrawal(int(parts[2]), False)
    await callback.message.edit_text(f"❌ Заявка #{parts[2]} отклонена")
    try: await callback.bot.send_message(int(parts[3]), "❌ Заявка отклонена. Stars возвращены.")
    except: pass

@router.message(Command("addcredits"))
async def cmd_addcredits(message: Message):
    if message.from_user.id != ADMIN_ID: return
    parts = message.text.split()
    if len(parts) != 3: await message.answer("Формат: /addcredits USER_ID AMOUNT"); return
    new_bal = await add_credits(int(parts[1]), int(parts[2]), "admin", "Ручное начисление")
    await message.answer(f"✅ Начислено *{parts[2]} кр.* Баланс: *{new_bal}*", parse_mode="Markdown")

# ══════════════════════════════════════════════════════
#  ЗАПУСК
# ══════════════════════════════════════════════════════

async def main():
    global anthropic_client, openai_client, deepseek_client

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    if not BOT_TOKEN: print("❌ BOT_TOKEN не задан"); return

    anthropic_client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_KEY) if ANTHROPIC_KEY else None
    if anthropic_client: logging.info("✅ Anthropic Claude подключён")

    if OPENAI_KEY:
        openai_client = AsyncOpenAI(api_key=OPENAI_KEY)
        logging.info("✅ OpenAI подключён (GPT-4o + DALL-E 3 + GPT Image 2)")

    if DEEPSEEK_KEY:
        deepseek_client = AsyncOpenAI(api_key=DEEPSEEK_KEY, base_url="https://api.deepseek.com")
        logging.info("✅ DeepSeek подключён")

    if AIML_KEY:
        logging.info("✅ AIML API подключён (Nano Banana + Kling + Suno)")

    await init_db()
    logging.info("✅ База данных готова")

    bot = Bot(token=BOT_TOKEN)
    dp  = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    logging.info(f"🚀 AuraAI Bot v3.0 запущен | @{BOT_USERNAME}")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    asyncio.run(main())
