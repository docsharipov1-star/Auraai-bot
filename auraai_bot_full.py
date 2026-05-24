"""
╔══════════════════════════════════════════════════════╗
║          AuraAI Bot — Полная версия                  ║
║  Python 3.11+ | aiogram 3.x | SQLite | Claude API   ║
║  Инструменты + Кредиты + Подписки + Рефералы         ║
╚══════════════════════════════════════════════════════╝

Установка:
  pip install aiogram anthropic aiosqlite python-dotenv

Создай файл .env рядом с этим файлом:
  BOT_TOKEN=токен_от_BotFather
  ANTHROPIC_KEY=sk-ant-...
  ADMIN_ID=твой_telegram_id
  BOT_USERNAME=имя_бота_без_собаки

Запуск:
  python auraai_bot_full.py
"""

import asyncio
import hashlib
import logging
import os
from datetime import datetime, timedelta

import aiosqlite
import anthropic
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton, LabeledPrice,
    Message, PreCheckoutQuery,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv

load_dotenv()

# ══════════════════════════════════════════════════════
#  КОНФИГ
# ══════════════════════════════════════════════════════

BOT_TOKEN      = os.getenv("BOT_TOKEN", "")
ANTHROPIC_KEY  = os.getenv("ANTHROPIC_KEY", "")
ADMIN_ID       = int(os.getenv("ADMIN_ID", "0"))
BOT_USERNAME   = os.getenv("BOT_USERNAME", "auraai_bot")
DB_PATH        = "auraai.db"
FREE_CREDITS   = 100
REFERRAL_BONUS = 50   # бонус новому пользователю за приход по реф-ссылке

PLANS = {
    "pro": {
        "name": "Pro", "emoji": "👑",
        "stars": 500, "credits": 5000, "days": 30,
        "description": "5 000 кредитов на 30 дней",
    },
    "team": {
        "name": "Team", "emoji": "💎",
        "stars": 1200, "credits": 15000, "days": 30,
        "description": "15 000 кредитов на 30 дней",
    },
}

CREDIT_PACKS = {
    "pack_500":   {"name": "500 кредитов",    "stars": 100,  "credits": 500},
    "pack_2000":  {"name": "2 000 кредитов",  "stars": 350,  "credits": 2000},
    "pack_5000":  {"name": "5 000 кредитов",  "stars": 800,  "credits": 5000},
    "pack_15000": {"name": "15 000 кредитов", "stars": 2000, "credits": 15000},
}

TOOL_COSTS = {
    "chat": 10, "copywriter": 20, "code": 25,
    "seo": 35, "translate": 15, "summarize": 15,
    "image_prompt": 10, "email": 20,
}

TOOL_NAMES = {
    "chat": "💬 AI Чат", "copywriter": "✍️ Копирайтер",
    "code": "💻 Код", "seo": "🔍 SEO",
    "translate": "🌐 Перевод", "summarize": "📝 Саммари",
    "image_prompt": "🖼 Image Prompt", "email": "📧 Email",
}

TOOL_HINTS = {
    "chat":         "Задай любой вопрос или поставь задачу:",
    "copywriter":   "Опиши что нужно написать (лэндинг, пост, реклама):",
    "code":         "Опиши задачу или вставь код для анализа:",
    "seo":          "Введи тему или URL для SEO-анализа:",
    "translate":    "Вставь текст для перевода (укажи язык если нужно):",
    "summarize":    "Вставь текст для краткого пересказа:",
    "image_prompt": "Опиши изображение которое хочешь создать:",
    "email":        "Опиши задачу для письма (кому, цель, тон):",
}

TOOL_PROMPTS = {
    "chat":         "Ты умный AI-ассистент. Отвечай полезно и по делу на языке пользователя.",
    "copywriter":   "Ты профессиональный копирайтер. Пиши продающие тексты: лэндинги, посты, рекламу. Форматируй красиво с заголовками и списками.",
    "code":         "Ты senior-разработчик. Пиши чистый код с комментариями. Объясняй решения. Поддерживаешь все языки программирования.",
    "seo":          "Ты SEO-специалист. Анализируй запросы, подбирай ключевые слова, пиши SEO-тексты и метатеги. Давай конкретные рекомендации.",
    "translate":    "Ты профессиональный переводчик. Переводи точно, сохраняй стиль и тон оригинала.",
    "summarize":    "Ты эксперт по саммаризации. Выделяй главное, структурируй, делай краткие выводы с ключевыми тезисами.",
    "image_prompt": "Ты эксперт по промптам для Midjourney и DALL-E. Создавай детальные художественные промпты на английском языке.",
    "email":        "Ты email-маркетолог. Пиши письма со структурой: тема, превью, тело, CTA. Убедительно и по делу.",
}

REFERRAL_LEVELS = {
    "user":    {"name": "Пользователь", "emoji": "👤", "percent": 10,
                "description": "10% от пополнений приглашённых друзей"},
    "partner": {"name": "Партнёр",      "emoji": "🤝", "percent": 25,
                "description": "25% — автоматически при 10+ рефералах"},
    "blogger": {"name": "Блогер",       "emoji": "🌟", "percent": 50,
                "description": "50% — назначается администратором"},
}

REFERRAL_MONTHS     = 12
MIN_WITHDRAW_STARS  = 100
PARTNER_MIN_REFS    = 10

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
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER,
                amount      INTEGER,
                type        TEXT,
                description TEXT,
                balance     INTEGER,
                created_at  TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS ai_requests (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      INTEGER,
                tool         TEXT,
                credits_used INTEGER,
                tokens_in    INTEGER DEFAULT 0,
                tokens_out   INTEGER DEFAULT 0,
                status       TEXT    DEFAULT 'success',
                created_at   TEXT    DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS payments (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER,
                type        TEXT,
                product_id  TEXT,
                stars       INTEGER,
                credits     INTEGER,
                status      TEXT DEFAULT 'completed',
                created_at  TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS referrals (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id  INTEGER NOT NULL,
                referee_id   INTEGER NOT NULL UNIQUE,
                created_at   TEXT DEFAULT CURRENT_TIMESTAMP,
                expires_at   TEXT
            );

            CREATE TABLE IF NOT EXISTS referral_earnings (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id    INTEGER NOT NULL,
                referee_id     INTEGER NOT NULL,
                payment_stars  INTEGER NOT NULL,
                commission_pct INTEGER NOT NULL,
                credits_earned INTEGER NOT NULL,
                stars_earned   INTEGER NOT NULL,
                created_at     TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS withdrawal_requests (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      INTEGER NOT NULL,
                stars_amount INTEGER NOT NULL,
                status       TEXT DEFAULT 'pending',
                admin_note   TEXT,
                created_at   TEXT DEFAULT CURRENT_TIMESTAMP,
                processed_at TEXT
            );
        """)
        await db.commit()

# ── Хелперы БД ────────────────────────────────────────

async def db_get(query: str, params: tuple = ()):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(query, params) as c:
            return await c.fetchone()

async def db_all(query: str, params: tuple = ()):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(query, params) as c:
            return await c.fetchall()

async def db_run(query: str, params: tuple = ()):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(query, params)
        await db.commit()

async def get_user(user_id: int):
    return await db_get("SELECT * FROM users WHERE id=?", (user_id,))

async def create_user(user_id: int, username: str, full_name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (id,username,full_name,credits,credits_total) VALUES (?,?,?,?,?)",
            (user_id, username, full_name, FREE_CREDITS, FREE_CREDITS)
        )
        await db.execute(
            "INSERT INTO transactions (user_id,amount,type,description,balance) VALUES (?,?,'bonus','Приветственные кредиты',?)",
            (user_id, FREE_CREDITS, FREE_CREDITS)
        )
        await db.commit()

async def get_balance(user_id: int) -> int:
    row = await db_get("SELECT credits FROM users WHERE id=?", (user_id,))
    return row["credits"] if row else 0

async def add_credits(user_id: int, amount: int, tx_type: str, description: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT credits FROM users WHERE id=?", (user_id,)) as c:
            row = await c.fetchone()
        cur = row["credits"] if row else 0
        new_bal = cur + amount
        await db.execute(
            "UPDATE users SET credits=?, credits_total=credits_total+? WHERE id=?",
            (new_bal, amount, user_id)
        )
        await db.execute(
            "INSERT INTO transactions (user_id,amount,type,description,balance) VALUES (?,?,?,?,?)",
            (user_id, amount, tx_type, description, new_bal)
        )
        await db.commit()
        return new_bal

async def use_credits(user_id: int, tool: str, cost: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT credits FROM users WHERE id=?", (user_id,)) as c:
            row = await c.fetchone()
        if not row or row["credits"] < cost:
            return False
        new_bal = row["credits"] - cost
        await db.execute("UPDATE users SET credits=? WHERE id=?", (new_bal, user_id))
        await db.execute(
            "INSERT INTO transactions (user_id,amount,type,description,balance) VALUES (?,?,'usage',?,?)",
            (user_id, -cost, f"Инструмент: {tool}", new_bal)
        )
        await db.commit()
        return True

async def set_plan(user_id: int, plan: str, credits: int, days: int):
    expires = (datetime.now() + timedelta(days=days)).isoformat()
    await db_run("UPDATE users SET plan=?, plan_expires=? WHERE id=?", (plan, expires, user_id))
    await add_credits(user_id, credits, "subscription", f"Подписка {plan}")

async def log_request(user_id: int, tool: str, credits: int, ti: int, to: int):
    await db_run(
        "INSERT INTO ai_requests (user_id,tool,credits_used,tokens_in,tokens_out) VALUES (?,?,?,?,?)",
        (user_id, tool, credits, ti, to)
    )

# ── Реферальные хелперы ───────────────────────────────

def make_ref_code(user_id: int) -> str:
    return hashlib.md5(f"aura_{user_id}_ref".encode()).hexdigest()[:8].upper()

async def get_or_create_ref_code(user_id: int) -> str:
    row = await db_get("SELECT ref_code FROM users WHERE id=?", (user_id,))
    if row and row["ref_code"]:
        return row["ref_code"]
    code = make_ref_code(user_id)
    await db_run("UPDATE users SET ref_code=? WHERE id=?", (code, user_id))
    return code

async def get_user_by_ref_code(code: str):
    return await db_get("SELECT * FROM users WHERE ref_code=?", (code.upper(),))

async def register_referral(referrer_id: int, referee_id: int) -> bool:
    if referrer_id == referee_id:
        return False
    existing = await db_get("SELECT id FROM referrals WHERE referee_id=?", (referee_id,))
    if existing:
        return False
    expires = (datetime.now() + timedelta(days=REFERRAL_MONTHS * 30)).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO referrals (referrer_id,referee_id,expires_at) VALUES (?,?,?)",
            (referrer_id, referee_id, expires)
        )
        await db.execute(
            "UPDATE users SET referrals_count=referrals_count+1 WHERE id=?", (referrer_id,)
        )
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT referrals_count,ref_level FROM users WHERE id=?", (referrer_id,)) as c:
            row = await c.fetchone()
        if row and row["referrals_count"] >= PARTNER_MIN_REFS and row["ref_level"] == "user":
            await db.execute("UPDATE users SET ref_level='partner' WHERE id=?", (referrer_id,))
        await db.commit()
    return True

async def process_commission(referee_id: int, payment_stars: int):
    ref = await db_get(
        "SELECT r.referrer_id, r.expires_at, u.ref_level FROM referrals r "
        "JOIN users u ON u.id=r.referrer_id WHERE r.referee_id=?",
        (referee_id,)
    )
    if not ref:
        return None
    if ref["expires_at"] and datetime.now() > datetime.fromisoformat(ref["expires_at"]):
        return None

    referrer_id    = ref["referrer_id"]
    level          = ref["ref_level"] or "user"
    pct            = REFERRAL_LEVELS[level]["percent"]
    stars_earned   = round(payment_stars * pct / 100)
    credits_earned = stars_earned * 10

    if stars_earned == 0:
        return None

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT credits FROM users WHERE id=?", (referrer_id,)) as c:
            row = await c.fetchone()
        cur = row["credits"] if row else 0
        new_bal = cur + credits_earned
        await db.execute(
            "UPDATE users SET credits=?, credits_total=credits_total+?, "
            "stars_balance=stars_balance+?, stars_earned_total=stars_earned_total+? WHERE id=?",
            (new_bal, credits_earned, stars_earned, stars_earned, referrer_id)
        )
        await db.execute(
            "INSERT INTO referral_earnings (referrer_id,referee_id,payment_stars,commission_pct,credits_earned,stars_earned) "
            "VALUES (?,?,?,?,?,?)",
            (referrer_id, referee_id, payment_stars, pct, credits_earned, stars_earned)
        )
        await db.execute(
            "INSERT INTO transactions (user_id,amount,type,description,balance) VALUES (?,?,'referral',?,?)",
            (referrer_id, credits_earned, f"Реф. комиссия {pct}% · {payment_stars} Stars", new_bal)
        )
        await db.commit()

    return {"referrer_id": referrer_id, "credits_earned": credits_earned,
            "stars_earned": stars_earned, "percent": pct, "level": level}

async def get_ref_stats(user_id: int) -> dict:
    user = await db_get(
        "SELECT ref_code,ref_level,referrals_count,stars_balance,stars_earned_total FROM users WHERE id=?",
        (user_id,)
    )
    if not user:
        return {}
    refs = await db_all(
        "SELECT u.full_name,u.username,r.created_at,r.expires_at,"
        "COALESCE(SUM(e.stars_earned),0) as earned "
        "FROM referrals r JOIN users u ON u.id=r.referee_id "
        "LEFT JOIN referral_earnings e ON e.referee_id=r.referee_id "
        "WHERE r.referrer_id=? GROUP BY r.referee_id ORDER BY r.created_at DESC LIMIT 20",
        (user_id,)
    )
    row = await db_get(
        "SELECT COALESCE(SUM(stars_earned),0) as s FROM referral_earnings "
        "WHERE referrer_id=? AND created_at>datetime('now','-30 days')",
        (user_id,)
    )
    return {
        "ref_code":           user["ref_code"],
        "level":              user["ref_level"] or "user",
        "referrals_count":    user["referrals_count"] or 0,
        "stars_balance":      user["stars_balance"] or 0,
        "stars_earned_total": user["stars_earned_total"] or 0,
        "earned_30d":         row["s"] if row else 0,
        "referrals":          refs,
    }

async def request_withdrawal(user_id: int, amount: int) -> dict:
    row = await db_get("SELECT stars_balance FROM users WHERE id=?", (user_id,))
    bal = row["stars_balance"] if row else 0
    if bal < MIN_WITHDRAW_STARS:
        return {"ok": False, "error": f"Минимум {MIN_WITHDRAW_STARS} Stars"}
    if amount > bal:
        return {"ok": False, "error": "Недостаточно Stars"}
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET stars_balance=stars_balance-? WHERE id=?", (amount, user_id))
        await db.execute("INSERT INTO withdrawal_requests (user_id,stars_amount) VALUES (?,?)", (user_id, amount))
        await db.commit()
    return {"ok": True}

async def set_ref_level(user_id: int, level: str) -> bool:
    if level not in REFERRAL_LEVELS:
        return False
    await db_run("UPDATE users SET ref_level=? WHERE id=?", (level, user_id))
    return True

async def get_pending_withdrawals():
    return await db_all(
        "SELECT w.id,w.user_id,w.stars_amount,w.created_at,u.username,u.full_name "
        "FROM withdrawal_requests w JOIN users u ON u.id=w.user_id "
        "WHERE w.status='pending' ORDER BY w.created_at"
    )

async def approve_withdrawal(req_id: int, approved: bool):
    if not approved:
        row = await db_get("SELECT user_id,stars_amount FROM withdrawal_requests WHERE id=?", (req_id,))
        if row:
            await db_run("UPDATE users SET stars_balance=stars_balance+? WHERE id=?",
                         (row["stars_amount"], row["user_id"]))
    status = "approved" if approved else "rejected"
    await db_run(
        "UPDATE withdrawal_requests SET status=?,processed_at=CURRENT_TIMESTAMP WHERE id=?",
        (status, req_id)
    )

# ── Админ-статистика ──────────────────────────────────

async def admin_stats():
    r1 = await db_get("SELECT COUNT(*) as c FROM users")
    r2 = await db_get("SELECT COUNT(*) as c FROM users WHERE plan!='free'")
    r3 = await db_get("SELECT COUNT(*) as c FROM ai_requests WHERE date(created_at)=date('now')")
    r4 = await db_get("SELECT COALESCE(SUM(stars),0) as s FROM payments WHERE status='completed'")
    return (r1["c"] if r1 else 0, r2["c"] if r2 else 0,
            r3["c"] if r3 else 0, r4["s"] if r4 else 0)

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
        [("🛠 Инструменты", "menu_tools"), ("💎 Кредиты",    "menu_credits")],
        [("👑 Подписки",    "menu_plans"),  ("🔗 Рефералы",   "menu_referral")],
        [("📊 Статистика",  "menu_stats"),  ("❓ Помощь",     "menu_help")],
    )

def tools_menu():
    b = InlineKeyboardBuilder()
    for tid, tname in TOOL_NAMES.items():
        cost = TOOL_COSTS.get(tid, 10)
        b.row(InlineKeyboardButton(text=f"{tname}  ·  {cost} кр.", callback_data=f"tool_{tid}"))
    b.row(InlineKeyboardButton(text="← Назад", callback_data="menu_main"))
    return b.as_markup()

def back_tools_kb():
    return kb(
        [("🔄 Ещё раз", "repeat_tool"), ("🛠 Инструменты", "menu_tools")],
        [("🏠 Меню", "menu_main")],
    )

def cancel_kb():
    return kb([("✖ Отмена", "menu_main")])

def credits_menu():
    return kb(
        [("📋 История", "credits_history"), ("⭐️ Купить Stars", "credits_buy")],
        [("← Назад", "menu_main")],
    )

def buy_credits_kb():
    b = InlineKeyboardBuilder()
    for pid, pack in CREDIT_PACKS.items():
        b.row(InlineKeyboardButton(
            text=f"{pack['name']}  ·  ⭐️ {pack['stars']}",
            callback_data=f"buy_credits_{pid}"
        ))
    b.row(InlineKeyboardButton(text="← Назад", callback_data="menu_credits"))
    return b.as_markup()

def plans_kb():
    b = InlineKeyboardBuilder()
    for pid, p in PLANS.items():
        b.row(InlineKeyboardButton(
            text=f"{p['emoji']} {p['name']}  ·  ⭐️ {p['stars']} / мес",
            callback_data=f"buy_plan_{pid}"
        ))
    b.row(InlineKeyboardButton(text="← Назад", callback_data="menu_main"))
    return b.as_markup()

def ref_menu_kb():
    return kb(
        [("📊 Статистика", "ref_stats"),    ("👥 Рефералы", "ref_list")],
        [("⭐️ Вывести Stars", "ref_withdraw"), ("❓ Как работает", "ref_howto")],
        [("← Меню", "menu_main")],
    )

# ══════════════════════════════════════════════════════
#  РОУТЕР И FSM
# ══════════════════════════════════════════════════════

router = Router()
ai_client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_KEY)
user_last_tool: dict[int, str] = {}

class ToolState(StatesGroup):
    waiting = State()

# ══════════════════════════════════════════════════════
#  /start
# ══════════════════════════════════════════════════════

@router.message(CommandStart())
async def cmd_start(message: Message):
    args = message.text.split()
    ref_code = None
    if len(args) > 1 and args[1].startswith("ref_"):
        ref_code = args[1].replace("ref_", "")

    user = await get_user(message.from_user.id)

    if not user:
        await create_user(
            message.from_user.id,
            message.from_user.username or "",
            message.from_user.full_name or ""
        )
        # Привязать реферала
        if ref_code:
            referrer = await get_user_by_ref_code(ref_code)
            if referrer and referrer["id"] != message.from_user.id:
                ok = await register_referral(referrer["id"], message.from_user.id)
                if ok:
                    await add_credits(message.from_user.id, REFERRAL_BONUS, "bonus",
                                      "Бонус за регистрацию по реф-ссылке")
                    # Уведомить реферера
                    try:
                        await message.bot.send_message(
                            referrer["id"],
                            f"🎉 По твоей ссылке зарегистрировался новый пользователь!\n"
                            f"Теперь ты будешь получать комиссию с его пополнений.",
                        )
                    except Exception:
                        pass

        bal = await get_balance(message.from_user.id)
        text = (
            f"✨ *Добро пожаловать в AuraAI!*\n\n"
            f"Я AI-ассистент с набором мощных инструментов.\n\n"
            f"🎁 Тебе начислено *{bal} кредитов* для старта\n\n"
            f"Выбери что хочешь сделать:"
        )
    else:
        bal = await get_balance(message.from_user.id)
        text = (
            f"👋 С возвращением, *{message.from_user.first_name}*!\n\n"
            f"💎 Баланс: *{bal} кредитов*\n\n"
            f"Чем займёмся?"
        )

    await message.answer(text, parse_mode="Markdown", reply_markup=main_menu())

# ══════════════════════════════════════════════════════
#  ГЛАВНОЕ МЕНЮ
# ══════════════════════════════════════════════════════

@router.callback_query(F.data == "menu_main")
async def cb_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    bal  = await get_balance(callback.from_user.id)
    user = await get_user(callback.from_user.id)
    plan_label = {"free": "Free", "pro": "👑 Pro", "team": "💎 Team"}.get(
        user["plan"] if user else "free", "Free"
    )
    text = (
        f"🏠 *Главное меню*\n\n"
        f"План: *{plan_label}*  |  Кредиты: *{bal}*\n\n"
        f"Выбери раздел:"
    )
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=main_menu())

# ══════════════════════════════════════════════════════
#  ИНСТРУМЕНТЫ
# ══════════════════════════════════════════════════════

@router.callback_query(F.data == "menu_tools")
async def cb_tools(callback: CallbackQuery):
    bal  = await get_balance(callback.from_user.id)
    await callback.message.edit_text(
        f"🛠 *Инструменты AuraAI*\n\n💎 Баланс: *{bal} кредитов*\n\nВыбери инструмент:",
        parse_mode="Markdown", reply_markup=tools_menu()
    )

@router.callback_query(F.data.startswith("tool_"))
async def cb_tool_select(callback: CallbackQuery, state: FSMContext):
    tool = callback.data.replace("tool_", "")
    cost = TOOL_COSTS.get(tool, 10)
    bal  = await get_balance(callback.from_user.id)

    if bal < cost:
        await callback.message.edit_text(
            f"❌ *Недостаточно кредитов*\n\nНужно: *{cost}* · У тебя: *{bal}*\n\nПополни баланс:",
            parse_mode="Markdown", reply_markup=credits_menu()
        )
        return

    await state.set_state(ToolState.waiting)
    await state.update_data(tool=tool)
    user_last_tool[callback.from_user.id] = tool

    await callback.message.edit_text(
        f"*{TOOL_NAMES[tool]}*  ·  💎 {cost} кредитов\n\n{TOOL_HINTS.get(tool, 'Введи запрос:')}",
        parse_mode="Markdown", reply_markup=cancel_kb()
    )

@router.callback_query(F.data == "repeat_tool")
async def cb_repeat(callback: CallbackQuery, state: FSMContext):
    tool = user_last_tool.get(callback.from_user.id)
    if not tool:
        await callback.message.edit_text("Выбери инструмент:", reply_markup=tools_menu())
        return
    cost = TOOL_COSTS.get(tool, 10)
    bal  = await get_balance(callback.from_user.id)
    if bal < cost:
        await callback.message.edit_text(
            f"❌ Недостаточно кредитов ({bal} из {cost})", reply_markup=cancel_kb()
        )
        return
    await state.set_state(ToolState.waiting)
    await state.update_data(tool=tool)
    await callback.message.edit_text(
        f"*{TOOL_NAMES[tool]}*  ·  💎 {cost} кредитов\n\n{TOOL_HINTS.get(tool, 'Введи запрос:')}",
        parse_mode="Markdown", reply_markup=cancel_kb()
    )

@router.message(ToolState.waiting)
async def process_tool(message: Message, state: FSMContext):
    data = await state.get_data()
    tool = data.get("tool", "chat")
    cost = TOOL_COSTS.get(tool, 10)

    ok = await use_credits(message.from_user.id, tool, cost)
    if not ok:
        await message.answer("❌ Недостаточно кредитов.", reply_markup=cancel_kb())
        return

    await state.clear()
    thinking = await message.answer(f"⏳ *{TOOL_NAMES[tool]}* думает...", parse_mode="Markdown")

    try:
        resp = await ai_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=TOOL_PROMPTS.get(tool, TOOL_PROMPTS["chat"]),
            messages=[{"role": "user", "content": message.text}]
        )
        result = resp.content[0].text
        ti, to = resp.usage.input_tokens, resp.usage.output_tokens
        bal    = await get_balance(message.from_user.id)
        await log_request(message.from_user.id, tool, cost, ti, to)

        # Разбить на части если текст длинный
        chunks = [result[i:i+3500] for i in range(0, len(result), 3500)]
        for i, chunk in enumerate(chunks):
            if i == 0:
                await thinking.edit_text(
                    f"*{TOOL_NAMES[tool]}*\n\n{chunk}\n\n"
                    f"💎 Потрачено: *{cost} кр.* · Остаток: *{bal} кр.*",
                    parse_mode="Markdown", reply_markup=back_tools_kb()
                )
            else:
                await message.answer(chunk, parse_mode="Markdown")

    except Exception as e:
        await add_credits(message.from_user.id, cost, "bonus", "Возврат: ошибка API")
        await thinking.edit_text(
            "⚠️ Ошибка AI. Кредиты возвращены. Попробуй ещё раз.",
            reply_markup=back_tools_kb()
        )
        logging.error(f"AI error: {e}")

# ══════════════════════════════════════════════════════
#  КРЕДИТЫ
# ══════════════════════════════════════════════════════

@router.callback_query(F.data == "menu_credits")
async def cb_credits(callback: CallbackQuery):
    bal = await get_balance(callback.from_user.id)
    await callback.message.edit_text(
        f"💎 *Кредиты*\n\nБаланс: *{bal} кредитов*\n\n"
        f"Кредиты списываются за каждый AI-запрос.\nКредиты не сгорают.",
        parse_mode="Markdown", reply_markup=credits_menu()
    )

@router.callback_query(F.data == "credits_history")
async def cb_history(callback: CallbackQuery):
    rows = await db_all(
        "SELECT amount,description,balance,created_at FROM transactions "
        "WHERE user_id=? ORDER BY created_at DESC LIMIT 10",
        (callback.from_user.id,)
    )
    bal   = await get_balance(callback.from_user.id)
    lines = [f"📋 *История*\n\nБаланс: *{bal} кр.*\n"]
    for r in rows:
        sign = "+" if r["amount"] > 0 else ""
        date = r["created_at"][:10] if r["created_at"] else ""
        lines.append(f"`{date}` {sign}{r['amount']} — {r['description']}")
    if not rows:
        lines.append("История пуста")
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="← Назад", callback_data="menu_credits"))
    await callback.message.edit_text("\n".join(lines), parse_mode="Markdown", reply_markup=b.as_markup())

@router.callback_query(F.data == "credits_buy")
async def cb_credits_buy(callback: CallbackQuery):
    await callback.message.edit_text(
        "⭐️ *Купить кредиты за Telegram Stars*\n\nКредиты зачисляются мгновенно и не сгорают.",
        parse_mode="Markdown", reply_markup=buy_credits_kb()
    )

# ══════════════════════════════════════════════════════
#  ПОДПИСКИ
# ══════════════════════════════════════════════════════

@router.callback_query(F.data == "menu_plans")
async def cb_plans(callback: CallbackQuery):
    user    = await get_user(callback.from_user.id)
    plan    = user["plan"] if user else "free"
    expires = user["plan_expires"] if user else None
    lines   = ["👑 *Подписки AuraAI*\n"]
    for pid, p in PLANS.items():
        active = "✅ " if plan == pid else ""
        lines.append(f"{active}*{p['emoji']} {p['name']}* — ⭐️ {p['stars']} Stars/мес")
        lines.append(f"  {p['description']}\n")
    if expires:
        lines.append(f"\n📅 Активна до: `{expires[:10]}`")
    await callback.message.edit_text(
        "\n".join(lines), parse_mode="Markdown", reply_markup=plans_kb()
    )

# ══════════════════════════════════════════════════════
#  СТАТИСТИКА
# ══════════════════════════════════════════════════════

@router.callback_query(F.data == "menu_stats")
async def cb_stats(callback: CallbackQuery):
    user  = await get_user(callback.from_user.id)
    bal   = await get_balance(callback.from_user.id)
    stats = await db_all(
        "SELECT tool,COUNT(*) as cnt,SUM(credits_used) as total FROM ai_requests "
        "WHERE user_id=? AND status='success' GROUP BY tool ORDER BY cnt DESC",
        (callback.from_user.id,)
    )
    lines = [
        f"📊 *Статистика*\n",
        f"💎 Баланс: *{bal} кр.*",
        f"🏅 Всего начислено: *{user['credits_total'] if user else 0} кр.*\n",
        "🔧 *По инструментам:*",
    ]
    for r in stats:
        name = TOOL_NAMES.get(r["tool"], r["tool"])
        lines.append(f"  {name}: {r['cnt']} запр. · {r['total'] or 0} кр.")
    if not stats:
        lines.append("  Пока нет запросов — попробуй инструменты!")
    await callback.message.edit_text(
        "\n".join(lines), parse_mode="Markdown", reply_markup=main_menu()
    )

# ══════════════════════════════════════════════════════
#  ПОМОЩЬ
# ══════════════════════════════════════════════════════

@router.callback_query(F.data == "menu_help")
async def cb_help(callback: CallbackQuery):
    await callback.message.edit_text(
        "❓ *Как пользоваться AuraAI*\n\n"
        "1️⃣ Выбери инструмент\n2️⃣ Опиши задачу\n3️⃣ Получи результат\n\n"
        "💎 *Кредиты* — расходуются на каждый запрос\n"
        "👑 *Подписки* — много кредитов по выгодной цене\n"
        "🔗 *Рефералы* — приглашай и зарабатывай\n\n"
        "🆘 Вопросы? Пиши @support",
        parse_mode="Markdown", reply_markup=main_menu()
    )

# ══════════════════════════════════════════════════════
#  ОПЛАТА ЧЕРЕЗ TELEGRAM STARS
# ══════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("buy_credits_"))
async def cb_invoice_credits(callback: CallbackQuery):
    pack_id = callback.data.replace("buy_credits_", "")
    pack    = CREDIT_PACKS.get(pack_id)
    if not pack:
        await callback.answer("Пакет не найден"); return
    await callback.bot.send_invoice(
        chat_id=callback.from_user.id,
        title=f"AuraAI — {pack['name']}",
        description=f"Пополнение баланса: {pack['credits']} кредитов",
        payload=f"credits_{pack_id}",
        currency="XTR",
        prices=[LabeledPrice(label=pack["name"], amount=pack["stars"])],
    )
    await callback.answer()

@router.callback_query(F.data.startswith("buy_plan_"))
async def cb_invoice_plan(callback: CallbackQuery):
    plan_id = callback.data.replace("buy_plan_", "")
    plan    = PLANS.get(plan_id)
    if not plan:
        await callback.answer("План не найден"); return
    await callback.bot.send_invoice(
        chat_id=callback.from_user.id,
        title=f"AuraAI {plan['name']} — 30 дней",
        description=plan["description"],
        payload=f"plan_{plan_id}",
        currency="XTR",
        prices=[LabeledPrice(label=f"AuraAI {plan['name']}", amount=plan["stars"])],
    )
    await callback.answer()

@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    await query.answer(ok=True)

@router.message(F.successful_payment)
async def on_payment(message: Message):
    payload = message.successful_payment.invoice_payload
    stars   = message.successful_payment.total_amount
    uid     = message.from_user.id

    if payload.startswith("credits_"):
        pack_id = payload.replace("credits_", "")
        pack    = CREDIT_PACKS.get(pack_id)
        if pack:
            new_bal = await add_credits(uid, pack["credits"], "purchase", f"Покупка: {pack['name']}")
            await message.answer(
                f"✅ *Оплата прошла!*\n\n"
                f"💎 Начислено: *+{pack['credits']} кредитов*\n"
                f"💰 Баланс: *{new_bal} кр.*\n"
                f"⭐️ Потрачено: {stars} Stars",
                parse_mode="Markdown", reply_markup=main_menu()
            )

    elif payload.startswith("plan_"):
        plan_id = payload.replace("plan_", "")
        plan    = PLANS.get(plan_id)
        if plan:
            await set_plan(uid, plan_id, plan["credits"], plan["days"])
            bal = await get_balance(uid)
            await message.answer(
                f"✅ *Подписка {plan['name']} активирована!*\n\n"
                f"💎 Начислено: *+{plan['credits']} кредитов*\n"
                f"💰 Баланс: *{bal} кр.*\n"
                f"📅 Действует 30 дней\n"
                f"⭐️ Потрачено: {stars} Stars",
                parse_mode="Markdown", reply_markup=main_menu()
            )

    # Реферальная комиссия
    commission = await process_commission(uid, stars)
    if commission:
        try:
            info = REFERRAL_LEVELS[commission["level"]]
            await message.bot.send_message(
                commission["referrer_id"],
                f"💰 *Реферальная комиссия!*\n\n"
                f"Твой реферал пополнил баланс на {stars} Stars.\n"
                f"{info['emoji']} Уровень *{info['name']}* ({commission['percent']}%)\n\n"
                f"Начислено: *+{commission['credits_earned']} кр.* "
                f"и ⭐️ *{commission['stars_earned']} Stars*",
                parse_mode="Markdown"
            )
        except Exception:
            pass

    # Сохранить платёж
    await db_run(
        "INSERT INTO payments (user_id,type,product_id,stars,credits,status) VALUES (?,?,?,?,?,?)",
        (uid, "purchase", payload, stars, 0, "completed")
    )

# ══════════════════════════════════════════════════════
#  РЕФЕРАЛЫ
# ══════════════════════════════════════════════════════

async def show_ref_main(uid: int, target, edit=False):
    ref_code = await get_or_create_ref_code(uid)
    stats    = await get_ref_stats(uid)
    level    = stats.get("level", "user")
    info     = REFERRAL_LEVELS[level]
    link     = f"https://t.me/{BOT_USERNAME}?start=ref_{ref_code}"
    text = (
        f"🔗 *Реферальная программа*\n\n"
        f"{info['emoji']} Уровень: *{info['name']}* — *{info['percent']}%* комиссия\n"
        f"📅 Срок: 12 месяцев с регистрации каждого реферала\n\n"
        f"👥 Рефералов: *{stats.get('referrals_count',0)}*\n"
        f"⭐️ Stars на балансе: *{stats.get('stars_balance',0)}*\n"
        f"📈 За 30 дней: *{stats.get('earned_30d',0)} Stars*\n"
        f"🏆 Всего: *{stats.get('stars_earned_total',0)} Stars*\n\n"
        f"🔗 *Твоя ссылка:*\n`{link}`"
    )
    if edit:
        await target.edit_text(text, parse_mode="Markdown", reply_markup=ref_menu_kb())
    else:
        await target.answer(text, parse_mode="Markdown", reply_markup=ref_menu_kb())

@router.message(Command("referral"))
async def cmd_referral(message: Message):
    await show_ref_main(message.from_user.id, message)

@router.callback_query(F.data == "menu_referral")
async def cb_referral(callback: CallbackQuery):
    await show_ref_main(callback.from_user.id, callback.message, edit=True)

@router.callback_query(F.data == "ref_stats")
async def cb_ref_stats(callback: CallbackQuery):
    stats  = await get_ref_stats(callback.from_user.id)
    level  = stats.get("level", "user")
    info   = REFERRAL_LEVELS[level]
    levels = list(REFERRAL_LEVELS.keys())
    idx    = levels.index(level)
    tip    = ""
    if idx < len(levels) - 1:
        nxt = levels[idx + 1]
        if nxt == "partner":
            need = max(0, PARTNER_MIN_REFS - stats.get("referrals_count", 0))
            tip  = f"\n\n📈 До уровня Партнёр: ещё *{need} рефералов*"
        elif nxt == "blogger":
            tip = "\n\n🌟 До Блогера: обратись к администратору"
    text = (
        f"📊 *Статистика рефералов*\n\n"
        f"{info['emoji']} *{info['name']}* — {info['percent']}%\n"
        f"👥 Рефералов: *{stats.get('referrals_count',0)}*\n\n"
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
        text = "👥 *Рефералы*\n\nПока никого нет.\nПоделись ссылкой — начни зарабатывать!"
    else:
        lines = [f"👥 *Рефералы* ({len(refs)} чел.)\n"]
        for r in refs:
            name    = r["full_name"] or r["username"] or "Аноним"
            earned  = r["earned"] or 0
            dt      = r["created_at"][:10] if r["created_at"] else ""
            expires = r["expires_at"][:10] if r["expires_at"] else ""
            lines.append(f"• *{name}* — ⭐️ {earned} Stars")
            lines.append(f"  {dt} · до {expires}")
        text = "\n".join(lines)
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="← Назад", callback_data="menu_referral"))
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=b.as_markup())

@router.callback_query(F.data == "ref_withdraw")
async def cb_ref_withdraw(callback: CallbackQuery):
    stats   = await get_ref_stats(callback.from_user.id)
    balance = stats.get("stars_balance", 0)
    b       = InlineKeyboardBuilder()
    text    = f"⭐️ *Вывод Stars*\n\nБаланс: *{balance}*\nМинимум: *{MIN_WITHDRAW_STARS}*\n\n"
    if balance >= MIN_WITHDRAW_STARS:
        text += "Выбери сумму:"
        seen = set()
        for a in [100, 500, 1000, balance]:
            if a <= balance and a not in seen:
                seen.add(a)
                b.row(InlineKeyboardButton(text=f"⭐️ {a} Stars", callback_data=f"withdraw_{a}"))
    else:
        text += f"Нужно ещё *{MIN_WITHDRAW_STARS - balance} Stars*"
    b.row(InlineKeyboardButton(text="← Назад", callback_data="menu_referral"))
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=b.as_markup())

@router.callback_query(F.data.startswith("withdraw_"))
async def cb_withdraw_confirm(callback: CallbackQuery):
    amount = int(callback.data.split("_")[1])
    result = await request_withdrawal(callback.from_user.id, amount)
    if result["ok"]:
        text = f"✅ *Заявка создана*\n\nСумма: *{amount} Stars*\nОбработка: до 24 часов."
    else:
        text = f"❌ {result['error']}"
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="← Назад", callback_data="menu_referral"))
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=b.as_markup())

@router.callback_query(F.data == "ref_howto")
async def cb_ref_howto(callback: CallbackQuery):
    text = (
        "❓ *Как работает реферальная программа*\n\n"
        "1️⃣ Получи свою ссылку в разделе Рефералы\n"
        "2️⃣ Поделись с друзьями или аудиторией\n"
        "3️⃣ Они регистрируются — становятся твоими рефералами\n"
        "4️⃣ При каждом их пополнении ты получаешь комиссию\n\n"
        "💰 *Уровни и комиссии:*\n"
        "👤 Пользователь — *10%*\n"
        "🤝 Партнёр — *25%* (от 10 рефералов, автоматически)\n"
        "🌟 Блогер — *50%* (по запросу у администратора)\n\n"
        "📅 *Срок:* 12 месяцев с регистрации каждого реферала\n\n"
        "⭐️ *Выплата:*\n"
        "• Кредиты зачисляются моментально\n"
        "• Stars накапливаются на балансе\n"
        "• Вывод Stars от 100 за 24 часа\n\n"
        "📈 *Пример для блогера:*\n"
        "100 подписчиков × 500 Stars × 50% = *25 000 Stars/мес* 🔥"
    )
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="← Назад", callback_data="menu_referral"))
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=b.as_markup())

# ══════════════════════════════════════════════════════
#  АДМИН-КОМАНДЫ
# ══════════════════════════════════════════════════════

@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    total, paid, today, stars = await admin_stats()
    await message.answer(
        f"🔐 *Админ-панель AuraAI*\n\n"
        f"👥 Всего пользователей: *{total}*\n"
        f"👑 Платных: *{paid}*\n"
        f"📨 Запросов сегодня: *{today}*\n"
        f"⭐️ Заработано Stars: *{stars}*",
        parse_mode="Markdown"
    )

@router.message(Command("setlevel"))
async def cmd_setlevel(message: Message):
    """Назначить реф-уровень: /setlevel USER_ID blogger"""
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.split()
    if len(parts) != 3:
        await message.answer("Формат: /setlevel USER_ID LEVEL\nУровни: user / partner / blogger")
        return
    target_id, level = int(parts[1]), parts[2].lower()
    ok = await set_ref_level(target_id, level)
    if ok:
        info = REFERRAL_LEVELS[level]
        await message.answer(
            f"✅ Пользователю {target_id} установлен уровень *{info['name']}* ({info['percent']}%)",
            parse_mode="Markdown"
        )
        try:
            await message.bot.send_message(
                target_id,
                f"🎉 *Твой реферальный уровень повышен!*\n\n"
                f"{info['emoji']} *{info['name']}* — {info['percent']}% комиссия\n"
                f"{info['description']}",
                parse_mode="Markdown"
            )
        except Exception:
            pass
    else:
        await message.answer("❌ Неверный уровень. Используй: user / partner / blogger")

@router.message(Command("withdrawals"))
async def cmd_withdrawals(message: Message):
    """Список заявок на вывод Stars"""
    if message.from_user.id != ADMIN_ID:
        return
    requests = await get_pending_withdrawals()
    if not requests:
        await message.answer("✅ Заявок на вывод нет")
        return
    for req in requests:
        name = req["full_name"] or req["username"] or str(req["user_id"])
        b = InlineKeyboardBuilder()
        b.row(
            InlineKeyboardButton(text="✅ Выплатить", callback_data=f"wd_ok_{req['id']}_{req['user_id']}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"wd_no_{req['id']}_{req['user_id']}"),
        )
        await message.answer(
            f"🔔 *Заявка #{req['id']}*\n"
            f"👤 {name} (`{req['user_id']}`)\n"
            f"⭐️ {req['stars_amount']} Stars\n"
            f"📅 {req['created_at'][:16]}",
            parse_mode="Markdown", reply_markup=b.as_markup()
        )

@router.callback_query(F.data.startswith("wd_ok_"))
async def cb_wd_approve(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    parts   = callback.data.split("_")
    req_id  = int(parts[2])
    user_id = int(parts[3])
    await approve_withdrawal(req_id, approved=True)
    await callback.message.edit_text(f"✅ Заявка #{req_id} одобрена")
    try:
        await callback.bot.send_message(
            user_id,
            "✅ *Твоя заявка на вывод Stars одобрена!*\nСредства придут в ближайшее время.",
            parse_mode="Markdown"
        )
    except Exception:
        pass

@router.callback_query(F.data.startswith("wd_no_"))
async def cb_wd_reject(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    parts   = callback.data.split("_")
    req_id  = int(parts[2])
    user_id = int(parts[3])
    await approve_withdrawal(req_id, approved=False)
    await callback.message.edit_text(f"❌ Заявка #{req_id} отклонена, Stars возвращены")
    try:
        await callback.bot.send_message(
            user_id,
            "❌ *Заявка отклонена.* Stars возвращены на баланс.",
            parse_mode="Markdown"
        )
    except Exception:
        pass

@router.message(Command("addcredits"))
async def cmd_addcredits(message: Message):
    """Начислить кредиты вручную: /addcredits USER_ID AMOUNT"""
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.split()
    if len(parts) != 3:
        await message.answer("Формат: /addcredits USER_ID AMOUNT")
        return
    target_id, amount = int(parts[1]), int(parts[2])
    new_bal = await add_credits(target_id, amount, "admin", "Ручное начисление администратором")
    await message.answer(f"✅ Начислено *{amount} кр.* Новый баланс: *{new_bal}*", parse_mode="Markdown")

# ══════════════════════════════════════════════════════
#  ЗАПУСК
# ══════════════════════════════════════════════════════

async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

    if not BOT_TOKEN:
        print("❌ BOT_TOKEN не задан в .env файле")
        return
    if not ANTHROPIC_KEY:
        print("❌ ANTHROPIC_KEY не задан в .env файле")
        return

    await init_db()
    logging.info("✅ База данных инициализирована")

    bot = Bot(token=BOT_TOKEN)
    dp  = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    logging.info(f"🚀 AuraAI Bot запущен | @{BOT_USERNAME}")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    asyncio.run(main())
