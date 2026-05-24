"""
╔══════════════════════════════════════════════════════╗
║          AuraAI Bot v2.0                             ║
║  Claude + DeepSeek + GPT Image 2 + DALL-E 3          ║
╚══════════════════════════════════════════════════════╝

Установка:
  pip install aiogram anthropic aiosqlite python-dotenv openai

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
import base64
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
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv

load_dotenv()

# ══════════════════════════════════════════════════════
#  КОНФИГ
# ══════════════════════════════════════════════════════

BOT_TOKEN     = os.getenv("BOT_TOKEN", "")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_KEY", "")
OPENAI_KEY    = os.getenv("OPENAI_KEY", "")
DEEPSEEK_KEY  = os.getenv("DEEPSEEK_KEY", "")
ADMIN_ID      = int(os.getenv("ADMIN_ID", "0"))
BOT_USERNAME  = os.getenv("BOT_USERNAME", "GetAuraAI_bot")
DB_PATH       = "auraai.db"
FREE_CREDITS  = 100
REFERRAL_BONUS = 50

# AI клиенты
anthropic_client = None
openai_client    = None
deepseek_client  = None

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

# ── Текстовые модели ──────────────────────────────────
TEXT_MODELS = {
    "claude":   {"name": "Claude Sonnet",  "emoji": "🅰", "cost": 10,  "provider": "anthropic"},
    "deepseek": {"name": "DeepSeek V3",    "emoji": "🐋", "cost": 5,   "provider": "deepseek"},
    "gpt4o":    {"name": "GPT-4o",         "emoji": "✳️", "cost": 15,  "provider": "openai"},
}

# ── Инструменты ───────────────────────────────────────
TOOLS = {
    "chat":         {"name": "💬 AI Чат",        "cost": 10,  "type": "text"},
    "copywriter":   {"name": "✍️ Копирайтер",    "cost": 20,  "type": "text"},
    "code":         {"name": "💻 Код",            "cost": 25,  "type": "text"},
    "seo":          {"name": "🔍 SEO",            "cost": 35,  "type": "text"},
    "translate":    {"name": "🌐 Перевод",        "cost": 15,  "type": "text"},
    "summarize":    {"name": "📝 Саммари",        "cost": 15,  "type": "text"},
    "email":        {"name": "📧 Email",          "cost": 20,  "type": "text"},
    "image_gpt":    {"name": "🖼 GPT Image 2",    "cost": 80,  "type": "image", "model": "gpt-image-1"},
    "image_dalle":  {"name": "🎨 DALL-E 3",       "cost": 50,  "type": "image", "model": "dall-e-3"},
}

TOOL_PROMPTS = {
    "chat":       "Ты умный AI-ассистент. Отвечай полезно и по делу на языке пользователя.",
    "copywriter": "Ты профессиональный копирайтер. Пиши продающие тексты: лэндинги, посты, рекламу.",
    "code":       "Ты senior-разработчик. Пиши чистый код с комментариями. Объясняй решения.",
    "seo":        "Ты SEO-специалист. Анализируй запросы, подбирай ключевые слова, пиши SEO-тексты.",
    "translate":  "Ты профессиональный переводчик. Переводи точно, сохраняй стиль оригинала.",
    "summarize":  "Ты эксперт по саммаризации. Выделяй главное, структурируй, делай краткие выводы.",
    "email":      "Ты email-маркетолог. Пиши письма со структурой: тема, превью, тело, CTA.",
}

TOOL_HINTS = {
    "chat":        "Задай любой вопрос:",
    "copywriter":  "Опиши что нужно написать (лэндинг, пост, реклама):",
    "code":        "Опиши задачу или вставь код для анализа:",
    "seo":         "Введи тему для SEO-анализа:",
    "translate":   "Вставь текст для перевода (укажи язык):",
    "summarize":   "Вставь текст для краткого пересказа:",
    "email":       "Опиши задачу для письма:",
    "image_gpt":   "Опиши картинку которую хочешь создать:\n\nПример: красивый закат над горами, фотореализм",
    "image_dalle": "Опиши картинку которую хочешь создать:\n\nПример: футуристический город будущего, цифровое искусство",
}

REFERRAL_LEVELS = {
    "user":    {"name": "Пользователь", "emoji": "👤", "percent": 10,  "description": "10% от пополнений рефералов"},
    "partner": {"name": "Партнёр",      "emoji": "🤝", "percent": 25,  "description": "25% — от 10 рефералов"},
    "blogger": {"name": "Блогер",       "emoji": "🌟", "percent": 50,  "description": "50% — назначается администратором"},
}

REFERRAL_MONTHS    = 12
MIN_WITHDRAW_STARS = 100
PARTNER_MIN_REFS   = 10

# ══════════════════════════════════════════════════════
#  БАЗА ДАННЫХ
# ══════════════════════════════════════════════════════

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id                  INTEGER PRIMARY KEY,
                username            TEXT,
                full_name           TEXT,
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
                referrer_id INTEGER NOT NULL,
                referee_id INTEGER NOT NULL UNIQUE,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                expires_at TEXT
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
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                processed_at TEXT
            );
        """)
        await db.commit()

async def db_get(q, p=()):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(q, p) as c:
            return await c.fetchone()

async def db_all(q, p=()):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(q, p) as c:
            return await c.fetchall()

async def db_run(q, p=()):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(q, p)
        await db.commit()

async def get_user(uid): return await db_get("SELECT * FROM users WHERE id=?", (uid,))
async def get_balance(uid):
    r = await db_get("SELECT credits FROM users WHERE id=?", (uid,))
    return r["credits"] if r else 0

async def create_user(uid, username, full_name):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (id,username,full_name,credits,credits_total) VALUES (?,?,?,?,?)",
            (uid, username, full_name, FREE_CREDITS, FREE_CREDITS)
        )
        await db.execute(
            "INSERT INTO transactions (user_id,amount,type,description,balance) VALUES (?,?,'bonus','Приветственные кредиты',?)",
            (uid, FREE_CREDITS, FREE_CREDITS)
        )
        await db.commit()

async def add_credits(uid, amount, tx_type, desc) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT credits FROM users WHERE id=?", (uid,)) as c:
            row = await c.fetchone()
        cur = row["credits"] if row else 0
        new = cur + amount
        await db.execute("UPDATE users SET credits=?, credits_total=credits_total+? WHERE id=?", (new, amount, uid))
        await db.execute(
            "INSERT INTO transactions (user_id,amount,type,description,balance) VALUES (?,?,?,?,?)",
            (uid, amount, tx_type, desc, new)
        )
        await db.commit()
        return new

async def use_credits(uid, tool, cost) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT credits FROM users WHERE id=?", (uid,)) as c:
            row = await c.fetchone()
        if not row or row["credits"] < cost: return False
        new = row["credits"] - cost
        await db.execute("UPDATE users SET credits=? WHERE id=?", (new, uid))
        await db.execute(
            "INSERT INTO transactions (user_id,amount,type,description,balance) VALUES (?,?,'usage',?,?)",
            (uid, -cost, f"Инструмент: {tool}", new)
        )
        await db.commit()
        return True

async def set_plan(uid, plan, credits, days):
    expires = (datetime.now() + timedelta(days=days)).isoformat()
    await db_run("UPDATE users SET plan=?, plan_expires=? WHERE id=?", (plan, expires, uid))
    await add_credits(uid, credits, "subscription", f"Подписка {plan}")

# ── Рефералы ──────────────────────────────────────────

def make_ref_code(uid): return hashlib.md5(f"aura_{uid}_ref".encode()).hexdigest()[:8].upper()

async def get_or_create_ref_code(uid):
    row = await db_get("SELECT ref_code FROM users WHERE id=?", (uid,))
    if row and row["ref_code"]: return row["ref_code"]
    code = make_ref_code(uid)
    await db_run("UPDATE users SET ref_code=? WHERE id=?", (code, uid))
    return code

async def get_user_by_ref_code(code):
    return await db_get("SELECT * FROM users WHERE ref_code=?", (code.upper(),))

async def register_referral(referrer_id, referee_id):
    if referrer_id == referee_id: return False
    if await db_get("SELECT id FROM referrals WHERE referee_id=?", (referee_id,)): return False
    expires = (datetime.now() + timedelta(days=REFERRAL_MONTHS * 30)).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO referrals (referrer_id,referee_id,expires_at) VALUES (?,?,?)", (referrer_id, referee_id, expires))
        await db.execute("UPDATE users SET referrals_count=referrals_count+1 WHERE id=?", (referrer_id,))
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT referrals_count,ref_level FROM users WHERE id=?", (referrer_id,)) as c:
            row = await c.fetchone()
        if row and row["referrals_count"] >= PARTNER_MIN_REFS and row["ref_level"] == "user":
            await db.execute("UPDATE users SET ref_level='partner' WHERE id=?", (referrer_id,))
        await db.commit()
    return True

async def process_commission(referee_id, payment_stars):
    ref = await db_get(
        "SELECT r.referrer_id,r.expires_at,u.ref_level FROM referrals r JOIN users u ON u.id=r.referrer_id WHERE r.referee_id=?",
        (referee_id,)
    )
    if not ref: return None
    if ref["expires_at"] and datetime.now() > datetime.fromisoformat(ref["expires_at"]): return None
    referrer_id = ref["referrer_id"]
    level = ref["ref_level"] or "user"
    pct = REFERRAL_LEVELS[level]["percent"]
    stars_earned = round(payment_stars * pct / 100)
    credits_earned = stars_earned * 10
    if stars_earned == 0: return None
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT credits FROM users WHERE id=?", (referrer_id,)) as c:
            row = await c.fetchone()
        cur = row["credits"] if row else 0
        new = cur + credits_earned
        await db.execute(
            "UPDATE users SET credits=?,credits_total=credits_total+?,stars_balance=stars_balance+?,stars_earned_total=stars_earned_total+? WHERE id=?",
            (new, credits_earned, stars_earned, stars_earned, referrer_id)
        )
        await db.execute(
            "INSERT INTO referral_earnings (referrer_id,referee_id,payment_stars,commission_pct,credits_earned,stars_earned) VALUES (?,?,?,?,?,?)",
            (referrer_id, referee_id, payment_stars, pct, credits_earned, stars_earned)
        )
        await db.execute(
            "INSERT INTO transactions (user_id,amount,type,description,balance) VALUES (?,?,'referral',?,?)",
            (referrer_id, credits_earned, f"Реф. комиссия {pct}% · {payment_stars} Stars", new)
        )
        await db.commit()
    return {"referrer_id": referrer_id, "credits_earned": credits_earned, "stars_earned": stars_earned, "percent": pct, "level": level}

async def get_ref_stats(uid):
    user = await db_get("SELECT ref_code,ref_level,referrals_count,stars_balance,stars_earned_total FROM users WHERE id=?", (uid,))
    if not user: return {}
    refs = await db_all(
        "SELECT u.full_name,u.username,r.created_at,r.expires_at,COALESCE(SUM(e.stars_earned),0) as earned "
        "FROM referrals r JOIN users u ON u.id=r.referee_id "
        "LEFT JOIN referral_earnings e ON e.referee_id=r.referee_id "
        "WHERE r.referrer_id=? GROUP BY r.referee_id ORDER BY r.created_at DESC LIMIT 20", (uid,)
    )
    row = await db_get(
        "SELECT COALESCE(SUM(stars_earned),0) as s FROM referral_earnings WHERE referrer_id=? AND created_at>datetime('now','-30 days')", (uid,)
    )
    return {
        "ref_code": user["ref_code"], "level": user["ref_level"] or "user",
        "referrals_count": user["referrals_count"] or 0,
        "stars_balance": user["stars_balance"] or 0,
        "stars_earned_total": user["stars_earned_total"] or 0,
        "earned_30d": row["s"] if row else 0, "referrals": refs,
    }

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
    await db_run("UPDATE users SET ref_level=? WHERE id=?", (level, uid))
    return True

async def get_pending_withdrawals():
    return await db_all(
        "SELECT w.id,w.user_id,w.stars_amount,w.created_at,u.username,u.full_name "
        "FROM withdrawal_requests w JOIN users u ON u.id=w.user_id WHERE w.status='pending' ORDER BY w.created_at"
    )

async def approve_withdrawal(req_id, approved):
    if not approved:
        row = await db_get("SELECT user_id,stars_amount FROM withdrawal_requests WHERE id=?", (req_id,))
        if row: await db_run("UPDATE users SET stars_balance=stars_balance+? WHERE id=?", (row["stars_amount"], row["user_id"]))
    await db_run(
        "UPDATE withdrawal_requests SET status=?,processed_at=CURRENT_TIMESTAMP WHERE id=?",
        ("approved" if approved else "rejected", req_id)
    )

async def admin_stats():
    r1 = await db_get("SELECT COUNT(*) as c FROM users")
    r2 = await db_get("SELECT COUNT(*) as c FROM users WHERE plan!='free'")
    r3 = await db_get("SELECT COUNT(*) as c FROM ai_requests WHERE date(created_at)=date('now')")
    r4 = await db_get("SELECT COALESCE(SUM(stars),0) as s FROM payments WHERE status='completed'")
    return (r1["c"] if r1 else 0, r2["c"] if r2 else 0, r3["c"] if r3 else 0, r4["s"] if r4 else 0)

# ══════════════════════════════════════════════════════
#  AI ФУНКЦИИ
# ══════════════════════════════════════════════════════

async def call_text_ai(prompt: str, system: str, model_id: str) -> str:
    model_info = TEXT_MODELS.get(model_id, TEXT_MODELS["claude"])
    provider = model_info["provider"]

    if provider == "anthropic":
        resp = await anthropic_client.messages.create(
            model="claude-sonnet-4-20250514", max_tokens=1024,
            system=system, messages=[{"role": "user", "content": prompt}]
        )
        return resp.content[0].text

    elif provider == "deepseek":
        resp = await deepseek_client.chat.completions.create(
            model="deepseek-chat", max_tokens=1024,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        )
        return resp.choices[0].message.content

    elif provider == "openai":
        resp = await openai_client.chat.completions.create(
            model="gpt-4o", max_tokens=1024,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        )
        return resp.choices[0].message.content

    return "Ошибка: неизвестная модель"

async def generate_image(prompt: str, model: str) -> bytes:
    if model == "gpt-image-1":
        resp = await openai_client.images.generate(
            model="gpt-image-1", prompt=prompt,
            n=1, size="1024x1024", quality="standard"
        )
        # Получить изображение по URL
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(resp.data[0].url) as r:
                return await r.read()

    elif model == "dall-e-3":
        resp = await openai_client.images.generate(
            model="dall-e-3", prompt=prompt,
            n=1, size="1024x1024", quality="standard"
        )
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(resp.data[0].url) as r:
                return await r.read()

# ══════════════════════════════════════════════════════
#  КЛАВИАТУРЫ
# ══════════════════════════════════════════════════════

def kb(*rows):
    b = InlineKeyboardBuilder()
    for row in rows:
        b.row(*[InlineKeyboardButton(text=t, callback_data=c) for t, c in row])
    return b.as_markup()

def main_menu():
    return kb(
        [("🛠 Инструменты", "menu_tools"), ("💎 Кредиты",   "menu_credits")],
        [("👑 Подписки",    "menu_plans"),  ("🔗 Рефералы",  "menu_referral")],
        [("📊 Статистика",  "menu_stats"),  ("❓ Помощь",    "menu_help")],
    )

def tools_menu():
    b = InlineKeyboardBuilder()
    # Текстовые инструменты
    b.row(InlineKeyboardButton(text="── Текст ──────────────", callback_data="noop"))
    for tid, t in TOOLS.items():
        if t["type"] == "text":
            b.row(InlineKeyboardButton(text=f"{t['name']}  ·  {t['cost']} кр.", callback_data=f"tool_{tid}"))
    # Картинки
    b.row(InlineKeyboardButton(text="── Изображения ────────", callback_data="noop"))
    for tid, t in TOOLS.items():
        if t["type"] == "image":
            b.row(InlineKeyboardButton(text=f"{t['name']}  ·  {t['cost']} кр.", callback_data=f"tool_{tid}"))
    b.row(InlineKeyboardButton(text="← Назад", callback_data="menu_main"))
    return b.as_markup()

def model_select_kb(tool_id):
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="Выбери модель AI:", callback_data="noop"))
    for mid, m in TEXT_MODELS.items():
        b.row(InlineKeyboardButton(
            text=f"{m['emoji']} {m['name']}  ·  +{m['cost']-TOOLS[tool_id]['cost']} кр." if m['cost'] > TOOLS[tool_id]['cost'] else f"{m['emoji']} {m['name']}  ·  {TOOLS[tool_id]['cost']+m['cost']} кр.",
            callback_data=f"model_{tool_id}_{mid}"
        ))
    b.row(InlineKeyboardButton(text="← Назад", callback_data="menu_tools"))
    return b.as_markup()

def back_tools_kb():
    return kb(
        [("🔄 Ещё раз", "repeat_tool"), ("🛠 Инструменты", "menu_tools")],
        [("🏠 Меню", "menu_main")],
    )

def cancel_kb(): return kb([("✖ Отмена", "menu_main")])

def credits_menu():
    return kb(
        [("📋 История", "credits_history"), ("⭐️ Купить", "credits_buy")],
        [("← Назад", "menu_main")],
    )

def buy_credits_kb():
    b = InlineKeyboardBuilder()
    for pid, pack in CREDIT_PACKS.items():
        b.row(InlineKeyboardButton(text=f"{pack['name']}  ·  ⭐️ {pack['stars']}", callback_data=f"buy_credits_{pid}"))
    b.row(InlineKeyboardButton(text="← Назад", callback_data="menu_credits"))
    return b.as_markup()

def plans_kb():
    b = InlineKeyboardBuilder()
    for pid, p in PLANS.items():
        b.row(InlineKeyboardButton(text=f"{p['emoji']} {p['name']}  ·  ⭐️ {p['stars']}/мес", callback_data=f"buy_plan_{pid}"))
    b.row(InlineKeyboardButton(text="← Назад", callback_data="menu_main"))
    return b.as_markup()

def ref_menu_kb():
    return kb(
        [("📊 Статистика", "ref_stats"),      ("👥 Рефералы", "ref_list")],
        [("⭐️ Вывести Stars", "ref_withdraw"), ("❓ Как работает", "ref_howto")],
        [("← Меню", "menu_main")],
    )

# ══════════════════════════════════════════════════════
#  РОУТЕР И FSM
# ══════════════════════════════════════════════════════

router = Router()
user_last_tool:  dict[int, str] = {}
user_last_model: dict[int, str] = {}

class ToolState(StatesGroup):
    waiting = State()

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
                    try:
                        await message.bot.send_message(referrer["id"], "🎉 По твоей ссылке зарегистрировался новый пользователь!")
                    except: pass
        bal = await get_balance(message.from_user.id)
        text = f"✨ *Добро пожаловать в AuraAI!*\n\n🎁 Тебе начислено *{bal} кредитов* для старта\n\nВыбери что хочешь сделать:"
    else:
        bal = await get_balance(message.from_user.id)
        text = f"👋 С возвращением, *{message.from_user.first_name}*!\n\n💎 Баланс: *{bal} кредитов*\n\nЧем займёмся?"

    await message.answer(text, parse_mode="Markdown", reply_markup=main_menu())

# ══════════════════════════════════════════════════════
#  МЕНЮ
# ══════════════════════════════════════════════════════

@router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery): await callback.answer()

@router.callback_query(F.data == "menu_main")
async def cb_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    bal = await get_balance(callback.from_user.id)
    user = await get_user(callback.from_user.id)
    plan_label = {"free": "Free", "pro": "👑 Pro", "team": "💎 Team"}.get(user["plan"] if user else "free", "Free")
    await callback.message.edit_text(
        f"🏠 *Главное меню*\n\nПлан: *{plan_label}*  |  Кредиты: *{bal}*\n\nВыбери раздел:",
        parse_mode="Markdown", reply_markup=main_menu()
    )

@router.callback_query(F.data == "menu_tools")
async def cb_tools(callback: CallbackQuery):
    bal = await get_balance(callback.from_user.id)
    await callback.message.edit_text(
        f"🛠 *Инструменты AuraAI v2*\n\n💎 Баланс: *{bal} кредитов*\n\nВыбери инструмент:",
        parse_mode="Markdown", reply_markup=tools_menu()
    )

# ══════════════════════════════════════════════════════
#  ИНСТРУМЕНТЫ — ВЫБОР МОДЕЛИ ДЛЯ ТЕКСТА
# ══════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("tool_"))
async def cb_tool_select(callback: CallbackQuery, state: FSMContext):
    tool_id = callback.data.replace("tool_", "")
    tool = TOOLS.get(tool_id)
    if not tool: return

    bal = await get_balance(callback.from_user.id)

    if tool["type"] == "image":
        # Для картинок сразу просим промпт
        if bal < tool["cost"]:
            await callback.message.edit_text(
                f"❌ Нужно *{tool['cost']} кр.* · У тебя *{bal} кр.*",
                parse_mode="Markdown", reply_markup=credits_menu()
            )
            return
        await state.set_state(ToolState.waiting)
        await state.update_data(tool=tool_id, model=tool.get("model", ""))
        user_last_tool[callback.from_user.id]  = tool_id
        user_last_model[callback.from_user.id] = tool.get("model", "")
        await callback.message.edit_text(
            f"*{tool['name']}*  ·  💎 {tool['cost']} кредитов\n\n{TOOL_HINTS.get(tool_id, 'Опиши картинку:')}",
            parse_mode="Markdown", reply_markup=cancel_kb()
        )
        return

    # Для текста — выбор модели
    if bal < tool["cost"]:
        await callback.message.edit_text(
            f"❌ Нужно *{tool['cost']} кр.* · У тебя *{bal} кр.*",
            parse_mode="Markdown", reply_markup=credits_menu()
        )
        return

    await callback.message.edit_text(
        f"*{tool['name']}*\n\nВыбери AI модель:",
        parse_mode="Markdown", reply_markup=model_select_kb(tool_id)
    )

@router.callback_query(F.data.startswith("model_"))
async def cb_model_select(callback: CallbackQuery, state: FSMContext):
    parts    = callback.data.split("_", 2)
    tool_id  = parts[1]
    model_id = parts[2]
    tool     = TOOLS.get(tool_id)
    model    = TEXT_MODELS.get(model_id)
    if not tool or not model: return

    # Итоговая стоимость = базовая стоимость инструмента + стоимость модели
    total_cost = tool["cost"] + model["cost"]
    bal = await get_balance(callback.from_user.id)

    if bal < total_cost:
        await callback.message.edit_text(
            f"❌ Нужно *{total_cost} кр.* · У тебя *{bal} кр.*",
            parse_mode="Markdown", reply_markup=credits_menu()
        )
        return

    await state.set_state(ToolState.waiting)
    await state.update_data(tool=tool_id, model=model_id, cost=total_cost)
    user_last_tool[callback.from_user.id]  = tool_id
    user_last_model[callback.from_user.id] = model_id

    await callback.message.edit_text(
        f"*{tool['name']}*  ·  {model['emoji']} {model['name']}\n"
        f"💎 {total_cost} кредитов\n\n{TOOL_HINTS.get(tool_id, 'Введи запрос:')}",
        parse_mode="Markdown", reply_markup=cancel_kb()
    )

@router.callback_query(F.data == "repeat_tool")
async def cb_repeat(callback: CallbackQuery, state: FSMContext):
    tool_id  = user_last_tool.get(callback.from_user.id)
    model_id = user_last_model.get(callback.from_user.id)
    if not tool_id:
        await callback.message.edit_text("Выбери инструмент:", reply_markup=tools_menu()); return
    tool = TOOLS.get(tool_id, {})
    if tool.get("type") == "image":
        cost = tool.get("cost", 50)
    else:
        model = TEXT_MODELS.get(model_id, TEXT_MODELS["claude"])
        cost  = tool.get("cost", 10) + model.get("cost", 10)
    bal = await get_balance(callback.from_user.id)
    if bal < cost:
        await callback.message.edit_text(f"❌ Недостаточно кредитов ({bal} из {cost})", reply_markup=cancel_kb()); return
    await state.set_state(ToolState.waiting)
    await state.update_data(tool=tool_id, model=model_id, cost=cost)
    await callback.message.edit_text(
        f"*{tool.get('name',tool_id)}*\n💎 {cost} кредитов\n\n{TOOL_HINTS.get(tool_id, 'Введи запрос:')}",
        parse_mode="Markdown", reply_markup=cancel_kb()
    )

# ══════════════════════════════════════════════════════
#  ОБРАБОТКА ЗАПРОСА
# ══════════════════════════════════════════════════════

@router.message(ToolState.waiting)
async def process_tool(message: Message, state: FSMContext):
    data     = await state.get_data()
    tool_id  = data.get("tool", "chat")
    model_id = data.get("model", "claude")
    tool     = TOOLS.get(tool_id, {})
    cost     = data.get("cost", tool.get("cost", 10))

    ok = await use_credits(message.from_user.id, tool_id, cost)
    if not ok:
        await message.answer("❌ Недостаточно кредитов.", reply_markup=cancel_kb()); return

    await state.clear()
    thinking = await message.answer(f"⏳ *{tool.get('name', tool_id)}* генерирует...", parse_mode="Markdown")

    try:
        if tool.get("type") == "image":
            # Генерация картинки
            image_model = tool.get("model", "dall-e-3")
            img_bytes = await generate_image(message.text, image_model)
            bal = await get_balance(message.from_user.id)

            await thinking.delete()
            await message.answer_photo(
                BufferedInputFile(img_bytes, filename="image.png"),
                caption=f"🖼 *{tool['name']}*\n\n💎 Потрачено: *{cost} кр.* · Остаток: *{bal} кр.*",
                parse_mode="Markdown", reply_markup=back_tools_kb()
            )
        else:
            # Текстовый запрос
            system = TOOL_PROMPTS.get(tool_id, "Ты полезный AI-ассистент.")
            result = await call_text_ai(message.text, system, model_id)
            bal    = await get_balance(message.from_user.id)
            model  = TEXT_MODELS.get(model_id, TEXT_MODELS["claude"])

            chunks = [result[i:i+3500] for i in range(0, len(result), 3500)]
            for i, chunk in enumerate(chunks):
                if i == 0:
                    await thinking.edit_text(
                        f"*{tool['name']}*  {model['emoji']} {model['name']}\n\n{chunk}\n\n"
                        f"💎 Потрачено: *{cost} кр.* · Остаток: *{bal} кр.*",
                        parse_mode="Markdown", reply_markup=back_tools_kb()
                    )
                else:
                    await message.answer(chunk)

        await db_run(
            "INSERT INTO ai_requests (user_id,tool,model,credits_used) VALUES (?,?,?,?)",
            (message.from_user.id, tool_id, model_id, cost)
        )

    except Exception as e:
        await add_credits(message.from_user.id, cost, "bonus", "Возврат: ошибка AI")
        await thinking.edit_text("⚠️ Ошибка AI. Кредиты возвращены. Попробуй ещё раз.", reply_markup=back_tools_kb())
        logging.error(f"AI error [{tool_id}/{model_id}]: {e}")

# ══════════════════════════════════════════════════════
#  КРЕДИТЫ / ПОДПИСКИ / ОПЛАТА
# ══════════════════════════════════════════════════════

@router.callback_query(F.data == "menu_credits")
async def cb_credits(callback: CallbackQuery):
    bal = await get_balance(callback.from_user.id)
    await callback.message.edit_text(
        f"💎 *Кредиты*\n\nБаланс: *{bal}*\n\nКредиты не сгорают.",
        parse_mode="Markdown", reply_markup=credits_menu()
    )

@router.callback_query(F.data == "credits_history")
async def cb_history(callback: CallbackQuery):
    rows = await db_all(
        "SELECT amount,description,balance,created_at FROM transactions WHERE user_id=? ORDER BY created_at DESC LIMIT 10",
        (callback.from_user.id,)
    )
    bal = await get_balance(callback.from_user.id)
    lines = [f"📋 *История*\n\nБаланс: *{bal} кр.*\n"]
    for r in rows:
        sign = "+" if r["amount"] > 0 else ""
        lines.append(f"`{r['created_at'][:10]}` {sign}{r['amount']} — {r['description']}")
    if not rows: lines.append("История пуста")
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="← Назад", callback_data="menu_credits"))
    await callback.message.edit_text("\n".join(lines), parse_mode="Markdown", reply_markup=b.as_markup())

@router.callback_query(F.data == "credits_buy")
async def cb_credits_buy(callback: CallbackQuery):
    await callback.message.edit_text(
        "⭐️ *Купить кредиты за Telegram Stars*\n\nКредиты зачисляются мгновенно.",
        parse_mode="Markdown", reply_markup=buy_credits_kb()
    )

@router.callback_query(F.data == "menu_plans")
async def cb_plans(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)
    plan = user["plan"] if user else "free"
    lines = ["👑 *Подписки AuraAI*\n"]
    for pid, p in PLANS.items():
        active = "✅ " if plan == pid else ""
        lines.append(f"{active}*{p['emoji']} {p['name']}* — ⭐️ {p['stars']}/мес\n  {p['description']}\n")
    await callback.message.edit_text("\n".join(lines), parse_mode="Markdown", reply_markup=plans_kb())

@router.callback_query(F.data == "menu_stats")
async def cb_stats(callback: CallbackQuery):
    user  = await get_user(callback.from_user.id)
    bal   = await get_balance(callback.from_user.id)
    stats = await db_all(
        "SELECT tool,model,COUNT(*) as cnt,SUM(credits_used) as total FROM ai_requests WHERE user_id=? GROUP BY tool,model ORDER BY cnt DESC",
        (callback.from_user.id,)
    )
    lines = [f"📊 *Статистика*\n\n💎 Баланс: *{bal} кр.*\n"]
    for r in stats:
        tname = TOOLS.get(r["tool"], {}).get("name", r["tool"])
        mname = TEXT_MODELS.get(r["model"], {}).get("name", r["model"] or "")
        lines.append(f"  {tname} {mname}: {r['cnt']} запр. · {r['total'] or 0} кр.")
    if not stats: lines.append("Пока нет запросов — попробуй инструменты!")
    await callback.message.edit_text("\n".join(lines), parse_mode="Markdown", reply_markup=main_menu())

@router.callback_query(F.data == "menu_help")
async def cb_help(callback: CallbackQuery):
    await callback.message.edit_text(
        "❓ *AuraAI v2*\n\n"
        "🟣 Claude — лучший для текста\n"
        "🔵 DeepSeek — самый дешёвый\n"
        "🟢 GPT-4o — универсальный\n"
        "🖼 GPT Image 2 — лучшие картинки\n"
        "🎨 DALL-E 3 — художественный стиль\n\n"
        "💎 Кредиты списываются за каждый запрос\n"
        "🔗 Рефералы — приглашай и зарабатывай",
        parse_mode="Markdown", reply_markup=main_menu()
    )

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
            await message.answer(
                f"✅ *Оплата прошла!*\n\n💎 +{pack['credits']} кредитов\n💰 Баланс: *{new_bal} кр.*",
                parse_mode="Markdown", reply_markup=main_menu()
            )
    elif payload.startswith("plan_"):
        plan = PLANS.get(payload.replace("plan_", ""))
        if plan:
            await set_plan(uid, payload.replace("plan_", ""), plan["credits"], plan["days"])
            bal = await get_balance(uid)
            await message.answer(
                f"✅ *{plan['name']} активирован!*\n\n💎 +{plan['credits']} кредитов\n💰 Баланс: *{bal} кр.*",
                parse_mode="Markdown", reply_markup=main_menu()
            )

    commission = await process_commission(uid, stars)
    if commission:
        try:
            info = REFERRAL_LEVELS[commission["level"]]
            await message.bot.send_message(
                commission["referrer_id"],
                f"💰 *Реферальная комиссия!*\n\n{info['emoji']} {info['name']} ({commission['percent']}%)\n"
                f"Начислено: *+{commission['credits_earned']} кр.* и ⭐️ *{commission['stars_earned']}*",
                parse_mode="Markdown"
            )
        except: pass

    await db_run("INSERT INTO payments (user_id,type,product_id,stars) VALUES (?,?,?,?)", (uid, "purchase", payload, stars))

# ══════════════════════════════════════════════════════
#  РЕФЕРАЛЫ
# ══════════════════════════════════════════════════════

async def show_ref_main(uid, target, edit=False):
    ref_code = await get_or_create_ref_code(uid)
    stats    = await get_ref_stats(uid)
    info     = REFERRAL_LEVELS[stats.get("level", "user")]
    link     = f"https://t.me/{BOT_USERNAME}?start=ref_{ref_code}"
    text = (
        f"🔗 *Реферальная программа*\n\n"
        f"{info['emoji']} *{info['name']}* — *{info['percent']}%*\n\n"
        f"👥 Рефералов: *{stats.get('referrals_count',0)}*\n"
        f"⭐️ Stars: *{stats.get('stars_balance',0)}*\n"
        f"📈 За 30 дней: *{stats.get('earned_30d',0)} Stars*\n\n"
        f"🔗 Твоя ссылка:\n`{link}`"
    )
    if edit: await target.edit_text(text, parse_mode="Markdown", reply_markup=ref_menu_kb())
    else: await target.answer(text, parse_mode="Markdown", reply_markup=ref_menu_kb())

@router.message(Command("referral"))
async def cmd_referral(message: Message): await show_ref_main(message.from_user.id, message)

@router.callback_query(F.data == "menu_referral")
async def cb_referral(callback: CallbackQuery): await show_ref_main(callback.from_user.id, callback.message, edit=True)

@router.callback_query(F.data == "ref_stats")
async def cb_ref_stats(callback: CallbackQuery):
    stats = await get_ref_stats(callback.from_user.id)
    info  = REFERRAL_LEVELS[stats.get("level", "user")]
    levels = list(REFERRAL_LEVELS.keys())
    idx = levels.index(stats.get("level", "user"))
    tip = ""
    if idx < len(levels)-1:
        nxt = levels[idx+1]
        tip = f"\n\n📈 До *{REFERRAL_LEVELS[nxt]['name']}*: ещё *{max(0,PARTNER_MIN_REFS-stats.get('referrals_count',0))} рефералов*" if nxt == "partner" else "\n\n🌟 До Блогера: обратись к администратору"
    text = (
        f"📊 *Статистика рефералов*\n\n"
        f"{info['emoji']} *{info['name']}* — {info['percent']}%\n"
        f"👥 Рефералов: *{stats.get('referrals_count',0)}*\n"
        f"⭐️ На балансе: *{stats.get('stars_balance',0)}*\n"
        f"📅 За 30 дней: *{stats.get('earned_30d',0)}*\n"
        f"🏆 Всего: *{stats.get('stars_earned_total',0)}*{tip}"
    )
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="← Назад", callback_data="menu_referral"))
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=b.as_markup())

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
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="← Назад", callback_data="menu_referral"))
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=b.as_markup())

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
        text += f"Нужно ещё *{MIN_WITHDRAW_STARS-bal} Stars*"
    b.row(InlineKeyboardButton(text="← Назад", callback_data="menu_referral"))
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=b.as_markup())

@router.callback_query(F.data.startswith("withdraw_"))
async def cb_withdraw(callback: CallbackQuery):
    amount = int(callback.data.split("_")[1])
    result = await request_withdrawal(callback.from_user.id, amount)
    text   = f"✅ Заявка на *{amount} Stars* создана. Обработка до 24 ч." if result["ok"] else f"❌ {result['error']}"
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="← Назад", callback_data="menu_referral"))
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=b.as_markup())

@router.callback_query(F.data == "ref_howto")
async def cb_ref_howto(callback: CallbackQuery):
    await callback.message.edit_text(
        "❓ *Реферальная программа*\n\n"
        "👤 Пользователь — *10%*\n"
        "🤝 Партнёр — *25%* (10+ рефералов)\n"
        "🌟 Блогер — *50%* (по запросу)\n\n"
        "📅 Срок: 12 месяцев\n"
        "⭐️ Вывод Stars от 100\n\n"
        "📈 Пример блогера:\n100 чел × 500 Stars × 50% = *25 000 Stars/мес* 🔥",
        parse_mode="Markdown", reply_markup=ref_menu_kb()
    )

# ══════════════════════════════════════════════════════
#  АДМИН
# ══════════════════════════════════════════════════════

@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id != ADMIN_ID: return
    total, paid, today, stars = await admin_stats()
    await message.answer(
        f"🔐 *Админ AuraAI v2*\n\n👥 Всего: *{total}*\n👑 Платных: *{paid}*\n📨 Сегодня: *{today}*\n⭐️ Stars: *{stars}*",
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
        try:
            await message.bot.send_message(int(parts[1]),
                f"🎉 Твой уровень повышен до *{info['name']}* — {info['percent']}%!", parse_mode="Markdown")
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
        await message.answer(
            f"🔔 *#{req['id']}* · {name}\n⭐️ {req['stars_amount']} Stars",
            parse_mode="Markdown", reply_markup=b.as_markup()
        )

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

    if not BOT_TOKEN:   print("❌ BOT_TOKEN не задан"); return
    if not ANTHROPIC_KEY: print("❌ ANTHROPIC_KEY не задан"); return

    # Инициализация AI клиентов
    anthropic_client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_KEY)

    if OPENAI_KEY:
        openai_client = AsyncOpenAI(api_key=OPENAI_KEY)
        logging.info("✅ OpenAI подключён (GPT-4o + GPT Image 2 + DALL-E 3)")
    else:
        logging.warning("⚠️ OPENAI_KEY не задан — GPT-4o и картинки недоступны")

    if DEEPSEEK_KEY:
        deepseek_client = AsyncOpenAI(api_key=DEEPSEEK_KEY, base_url="https://api.deepseek.com")
        logging.info("✅ DeepSeek подключён")
    else:
        logging.warning("⚠️ DEEPSEEK_KEY не задан — DeepSeek недоступен")

    await init_db()
    logging.info("✅ База данных готова")

    bot = Bot(token=BOT_TOKEN)
    dp  = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    logging.info(f"🚀 AuraAI Bot v2.0 запущен | @{BOT_USERNAME}")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    asyncio.run(main())
