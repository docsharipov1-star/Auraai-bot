"""
╔══════════════════════════════════════════════════════╗
║          Vatan AI Bot v3.0 — Syntx AI Style            ║
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
from aiogram.filters import Command, CommandStart, StateFilter
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
YOOKASSA_TOKEN = os.getenv("YOOKASSA_TOKEN", "")  # provider token из BotFather (ЮKassa)
DB_PATH       = "/app/data/auraai.db"
FREE_CREDITS  = 150
REFERRAL_BONUS = 50

anthropic_client = None
openai_client    = None
deepseek_client  = None
kie_client       = None

PLANS = {
    "basic":   {"name": "Basic",   "emoji": "⭐️", "stars": 325,  "rub": 390,  "credits": 2000, "days": 30, "unlimited": False, "description": "2 000 кредитов на 30 дней"},
    "pro":     {"name": "Pro",     "emoji": "👑", "stars": 900,  "rub": 1090, "credits": 4500, "days": 30, "unlimited": False, "discount": 25, "description": "4 500 кредитов + скидка 25% на фото и картинки"},
    "premium": {"name": "Premium", "emoji": "💎", "stars": 1900, "rub": 2290, "credits": 9000, "days": 30, "unlimited": True, "discount": 50, "description": "9 000 кредитов + БЕЗЛИМИТ на AI-чат + скидка 50% на фото и картинки"},
}

# Годовые подписки — 2 месяца в подарок (платишь ~за 10, кредиты сразу за год)
PLANS_ANNUAL = {
    "basic":   {"name": "Basic год",   "emoji": "⭐️", "stars": 3250,  "rub": 3900,  "credits": 24000,  "days": 365, "base": "basic"},
    "pro":     {"name": "Pro год",     "emoji": "👑", "stars": 9000,  "rub": 10900, "credits": 54000,  "days": 365, "base": "pro"},
    "premium": {"name": "Premium год", "emoji": "💎", "stars": 19000, "rub": 22900, "credits": 108000, "days": 365, "base": "premium"},
}

# Курс по нейросетям
COURSE = {"name": "Курс «Заработок на ИИ-картинках»", "rub": 2900, "stars": 2400, "credits": 1000}

SALES_PROMPT = (
    "Ты — дружелюбный и уверенный менеджер по продажам онлайн-курса Vatan AI. "
    "Твоя задача — помочь человеку и мягко довести его до покупки курса.\n\n"
    "О КУРСЕ:\n"
    "• Название: курс «Заработок на ИИ-картинках».\n"
    "• Цена: 2 900₽. Можно оплатить картой (рубли) или Telegram Stars прямо в боте.\n"
    "• Для кого: для новичков с нуля — студентов, предпринимателей, всех кто хочет новую профессию или подработку из дома. Опыт и диплом не нужны, нужен только телефон.\n"
    "• Что внутри: как обрабатывать фото, делать рекламу и карточки товаров, оживлять снимки в видео, и как брать на этом платные заказы.\n"
    "• Результат: после курса человек умеет делать ИИ-визуал и может брать заказы или делать визуал для своего бизнеса без дизайнера.\n"
    "• Бонус: при покупке курса начисляется 1 000 кредитов на бота Vatan AI, чтобы сразу практиковаться.\n\n"
    "КАК ОБЩАТЬСЯ:\n"
    "• Отвечай коротко, тепло, по-человечески, на «ты». 2-4 предложения. Не повторяй один и тот же текст — каждый ответ разный.\n"
    "• ВСЕГДА заканчивай ответ встречным вопросом, чтобы продолжить диалог (например: «А ты для себя хочешь освоить или для заработка?», «Какой у тебя сейчас доход хочешь добавить?»). Это помогает дожимать.\n"
    "• Отрабатывай возражения честно: «дорого» — покажи ценность и сколько можно заработать, окупится с первых заказов; «не получится» — успокой, всё на телефоне в пару нажатий, поддержка есть; «это развод?» — объясни что это реальная новая профессия, покажи логику.\n"
    "• Веди как живой менеджер: интересуйся ситуацией человека, и под неё показывай выгоду курса.\n"
    "• Никогда не ври и не обещай гарантированных доходов. Будь честным.\n"
    "• Когда чувствуешь интерес — прямо предлагай нажать кнопку «Купить курс» внизу.\n"
    "• Если спрашивают не про курс — кратко ответь и верни разговор к курсу.\n"
    "• Пиши на том языке, на котором пишет человек (русский или таджикский)."
)

SUPPORT_PROMPT = (
    "Ты — дружелюбный агент поддержки Telegram-бота Vatan AI. Отвечай тепло, коротко и по делу, на «ты», на языке пользователя (русский или таджикский).\n\n"
    "ЧТО УМЕЕТ БОТ Vatan AI:\n"
    "• 💡 Текстовый AI-чат (Claude, GPT-4o, DeepSeek) — вопросы, тексты, помощь.\n"
    "• 🎨 Дизайн с ИИ — генерация картинок (Nano Banana, GPT Image, DALL-E), редактирование фото, соединение нескольких фото.\n"
    "• 🎬 Видео будущего — генерация видео (Seedance, Kling), оживление фото в видео, ИИ-аватар с синхронизацией губ (Kling Avatar).\n"
    "• 🎙 Аудио с ИИ — генерация музыки (Lyria) и озвучка текста голосом (TTS).\n"
    "• 🗂 Хранитель изображений — сохранение работ.\n"
    "• 🎓 Обучение — курс по заработку на нейросетях.\n"
    "• 🔗 Рефералы — приглашаешь друзей и получаешь бонусы.\n\n"
    "КРЕДИТЫ И ОПЛАТА:\n"
    "• Всё работает на кредитах, они списываются за каждую генерацию. На старте даются бесплатные кредиты.\n"
    "• Пополнить: Профиль → 💎 Купить кредиты. Оплата картой (рубли) или Telegram Stars.\n"
    "• Есть пакеты кредитов и подписки (Basic, Pro, Premium), а также годовые тарифы со скидкой.\n"
    "• Кредиты не сгорают.\n\n"
    "ЧАСТЫЕ ВОПРОСЫ:\n"
    "• Генерация видео/музыки/аватара идёт в фоне 2-4 минуты — можно пользоваться ботом, результат придёт сам.\n"
    "• Если генерация не удалась — кредиты автоматически возвращаются.\n"
    "• Чтобы отредактировать фото: Дизайн с ИИ → Редактировать фото → отправить фото → описать что изменить.\n"
    "• Видео из фото: Видео будущего → Фото в видео → отправить фото → выбрать формат → описать движение.\n"
    "• Закончились кредиты — пополни в Профиле.\n\n"
    "ПРАВИЛА:\n"
    "• Помогай решить проблему пошагово и просто.\n"
    "• Если вопрос про оплату/возврат, который ты не можешь решить сам, или серьёзная техническая проблема — скажи, что передашь вопрос администратору, и предложи написать ему.\n"
    "• Не выдумывай функции, которых нет. Если не знаешь — честно скажи и предложи связаться с админом.\n"
    "• Будь кратким: 2-4 предложения."
)

CREDIT_PACKS = {
    "pack_500":   {"name": "500 кредитов",    "stars": 80,   "rub": 99,   "credits": 500},
    "pack_2000":  {"name": "2 000 кредитов",  "stars": 290,  "rub": 349,  "credits": 2000},
    "pack_5000":  {"name": "5 000 кредитов",  "stars": 650,  "rub": 799,  "credits": 5000},
    "pack_15000": {"name": "15 000 кредитов", "stars": 1800, "rub": 2199, "credits": 15000},
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

import pathlib
pathlib.Path("/app/data").mkdir(parents=True, exist_ok=True)

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
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_chat_history_user ON chat_history(user_id);
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
        """)
        await db.commit()

async def setting_get(key, default=None):
    row = await db_get("SELECT value FROM app_settings WHERE key=?", (key,))
    return row["value"] if row else default

async def setting_set(key, value):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO app_settings (key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=?", (key, value, value))
        await db.commit()

# ══════════════════════════════════════════════════════
#  API «МОЙ НАЛОГ» (НПД) — автоматическая регистрация чеков
#  Неофициальный API lknpd.nalog.ru. Токен живёт ~1 час, обновляется по refreshToken.
# ══════════════════════════════════════════════════════
NALOG_API = "https://lknpd.nalog.ru/api/v1"
NALOG_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"

async def nalog_device_info():
    dev_id = await setting_get("nalog_device_id")
    if not dev_id:
        import uuid as _uuid
        dev_id = _uuid.uuid4().hex
        await setting_set("nalog_device_id", dev_id)
    return {
        "sourceDeviceId": dev_id,
        "sourceType": "WEB",
        "appVersion": "1.0.0",
        "metaDetails": {"userAgent": NALOG_UA},
    }

async def nalog_request_sms(phone: str) -> str:
    """Шаг 1: запросить SMS-код. Возвращает challengeToken."""
    dev = await nalog_device_info()
    now = datetime.now().isoformat()[:-3] + "Z"
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(f"{NALOG_API}/auth/challenge", json={
            "phone": phone, "requestTime": now, "deviceInfo": dev,
        }, headers={"User-Agent": NALOG_UA})
        r.raise_for_status()
        data = r.json()
    return data["challengeToken"]

async def nalog_verify_sms(phone: str, code: str, challenge_token: str):
    """Шаг 2: подтвердить код. Сохраняет refreshToken и ИНН."""
    dev = await nalog_device_info()
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(f"{NALOG_API}/auth/challenge/verify", json={
            "phone": phone, "code": code, "challengeToken": challenge_token, "deviceInfo": dev,
        }, headers={"User-Agent": NALOG_UA})
        r.raise_for_status()
        data = r.json()
    refresh = data.get("refreshToken")
    if not refresh:
        raise Exception(f"Нет refreshToken в ответе: {list(data.keys())}")
    await setting_set("nalog_refresh_token", refresh)
    inn = (data.get("profile") or {}).get("inn")
    if inn:
        await setting_set("nalog_inn", str(inn))
    await setting_set("nalog_phone", phone)
    return inn

async def nalog_access_token() -> str:
    """Возвращает действующий access token (обновляет по refreshToken при необходимости)."""
    import time as _time
    cached = await setting_get("nalog_access_token")
    expires = await setting_get("nalog_token_expires")
    if cached and expires and float(expires) > _time.time() + 60:
        return cached
    refresh = await setting_get("nalog_refresh_token")
    if not refresh:
        raise Exception("Не авторизован в «Мой налог». Выполни /nalog_login")
    dev = await nalog_device_info()
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(f"{NALOG_API}/auth/token", json={
            "refreshToken": refresh, "deviceInfo": dev,
        }, headers={"User-Agent": NALOG_UA})
        r.raise_for_status()
        data = r.json()
    token = data.get("token")
    if not token:
        raise Exception("Не удалось обновить токен «Мой налог»")
    if data.get("refreshToken"):
        await setting_set("nalog_refresh_token", data["refreshToken"])
    await setting_set("nalog_access_token", token)
    await setting_set("nalog_token_expires", str(_time.time() + 50 * 60))  # ~50 мин
    return token

async def nalog_add_income(name: str, amount: float) -> str:
    """Регистрирует доход в «Мой налог», возвращает ссылку на чек (или '' при ошибке)."""
    token = await nalog_access_token()
    inn = await setting_get("nalog_inn")
    dev = await nalog_device_info()
    now = datetime.now().isoformat()[:-3] + "+03:00"
    body = {
        "operationTime": now,
        "requestTime": now,
        "services": [{"name": name, "amount": round(float(amount), 2), "quantity": 1}],
        "totalAmount": str(round(float(amount), 2)),
        "client": {"contactPhone": None, "displayName": None, "incomeType": "FROM_INDIVIDUAL", "inn": None},
        "paymentType": "CASH",
        "ignoreMaxTotalIncomeRestriction": False,
        "deviceInfo": dev,
    }
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(f"{NALOG_API}/income", json=body,
                              headers={"Authorization": f"Bearer {token}", "User-Agent": NALOG_UA})
        r.raise_for_status()
        data = r.json()
    uuid_r = data.get("approvedReceiptUuid")
    if not uuid_r or not inn:
        return ""
    return f"{NALOG_API}/receipt/{inn}/{uuid_r}/print"

async def nalog_is_connected() -> bool:
    return bool(await setting_get("nalog_refresh_token"))

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

# Инструменты которые бесплатны для Premium (безлимит)
UNLIMITED_TOOLS = {"chat"}  # Premium: безлимит только на чат (дёшево и безопасно)
PREMIUM_DISCOUNT_TOOLS = {"img2img", "img2img_remix", "combine", "image_nano", "image_gpt", "image_dalle"}  # Premium: -50%

async def is_premium(uid) -> bool:
    """Проверка активной Premium-подписки"""
    user = await db_get("SELECT plan, plan_expires FROM users WHERE id=?", (uid,))
    if not user or user["plan"] != "premium":
        return False
    if not user["plan_expires"]:
        return False
    try:
        if datetime.fromisoformat(user["plan_expires"]) < datetime.now():
            return False
    except Exception:
        return False
    return True

async def get_active_plan(uid) -> str:
    """Возвращает активный план: free / basic / pro / premium"""
    user = await db_get("SELECT plan, plan_expires FROM users WHERE id=?", (uid,))
    if not user or not user["plan"] or user["plan"] == "free":
        return "free"
    if not user["plan_expires"]:
        return "free"
    try:
        if datetime.fromisoformat(user["plan_expires"]) < datetime.now():
            return "free"
    except Exception:
        return "free"
    return user["plan"]

async def use_credits(uid, tool, cost) -> bool:
    plan = await get_active_plan(uid)
    # Premium — безлимит на чат
    if tool in UNLIMITED_TOOLS and plan == "premium":
        await db_run("INSERT INTO transactions (user_id,amount,type,description,balance) VALUES (?,?,'usage',?,?)",
                     (uid, 0, f"Premium безлимит: {tool}", await get_balance(uid)))
        return True
    # Скидка на изображения и фото: Premium -50%, Pro -25%
    if tool in PREMIUM_DISCOUNT_TOOLS:
        if plan == "premium":
            cost = max(1, cost // 2)
        elif plan == "pro":
            cost = max(1, int(cost * 0.75))
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

async def call_text_ai(prompt: str, system: str, model_id: str, uid: int = 0, use_history: bool = False, image_url: str = None, history_msgs: list = None, timeout_s: int = 15) -> str:
    model_info = TEXT_MODELS.get(model_id, TEXT_MODELS["claude"])
    provider = model_info["provider"]

    # Построить контент сообщения (текст + опционально картинка)
    if image_url and provider == "anthropic":
        # Скачать картинку и передать как base64
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(image_url)
            r.raise_for_status()
            img_b64 = base64.b64encode(r.content).decode()
            content_type = r.headers.get("content-type", "image/jpeg").split(";")[0]
        user_content = [
            {"type": "image", "source": {"type": "base64", "media_type": content_type, "data": img_b64}},
            {"type": "text", "text": prompt}
        ]
    elif image_url and provider in ("openai", "deepseek"):
        user_content = [
            {"type": "image_url", "image_url": {"url": image_url}},
            {"type": "text", "text": prompt}
        ]
    else:
        user_content = prompt

    if history_msgs is not None:
        messages = history_msgs + [{"role": "user", "content": user_content}]
    elif use_history and uid:
        history = await get_history(uid)
        messages = history + [{"role": "user", "content": user_content}]
    else:
        messages = [{"role": "user", "content": user_content}]

    try:
        if provider == "anthropic" and anthropic_client:
            resp = await asyncio.wait_for(
                anthropic_client.messages.create(
                    model="claude-sonnet-4-20250514", max_tokens=1024,
                    system=system, messages=messages),
                timeout=timeout_s
            )
            result = resp.content[0].text
        elif provider == "deepseek" and deepseek_client:
            resp = await asyncio.wait_for(
                deepseek_client.chat.completions.create(
                    model="deepseek-chat", max_tokens=1024,
                    messages=[{"role": "system", "content": system}] + messages),
                timeout=timeout_s
            )
            result = resp.choices[0].message.content
        elif provider == "openai" and openai_client:
            resp = await asyncio.wait_for(
                openai_client.chat.completions.create(
                    model="gpt-4o", max_tokens=1024,
                    messages=[{"role": "system", "content": system}] + messages),
                timeout=timeout_s
            )
            result = resp.choices[0].message.content
        else:
            return "❌ Модель недоступна. Проверь API ключи."

        if history_msgs is None and use_history and uid:
            await add_to_history(uid, "user", prompt)
            await add_to_history(uid, "assistant", result)

        return result

    except asyncio.TimeoutError:
        logging.error(f"Text AI timeout [{model_id}]")
        raise Exception("Превышено время ожидания. Попробуй ещё раз.")
    except Exception as e:
        logging.error(f"Text AI error [{model_id}]: {e}")
        raise

import base64

def _aspect_to_size(aspect: str) -> str:
    """Конвертирует формат в размер для OpenAI"""
    return {
        "1:1": "1024x1024",
        "16:9": "1792x1024",
        "9:16": "1024x1792",
        "4:3": "1792x1024",
        "3:4": "1024x1792",
    }.get(aspect, "1024x1024")

async def generate_image_dalle(prompt: str, aspect: str = "1:1") -> bytes:
    if not openai_client:
        raise Exception("OpenAI ключ не настроен")
    resp = await asyncio.wait_for(
        openai_client.images.generate(
            model="dall-e-3", prompt=prompt,
            n=1, size=_aspect_to_size(aspect), quality="standard",
            response_format="b64_json"
        ), timeout=30
    )
    return base64.b64decode(resp.data[0].b64_json)

async def generate_image_gpt(prompt: str, aspect: str = "1:1") -> bytes:
    if not openai_client:
        raise Exception("OpenAI ключ не настроен")
    resp = await asyncio.wait_for(
        openai_client.images.generate(
            model="gpt-image-1", prompt=prompt,
            n=1, size=_aspect_to_size(aspect)
        ), timeout=30
    )
    if resp.data[0].b64_json:
        return base64.b64decode(resp.data[0].b64_json)
    url = resp.data[0].url
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.content

async def aiml_request(endpoint: str, payload: dict) -> dict:
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

async def generate_nano_banana(prompt: str, aspect: str = "1:1") -> bytes:
    data = await aiml_request("v1/images/generations", {
        "model": "google/nano-banana-pro",
        "prompt": prompt,
        "aspect_ratio": aspect,
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

async def generate_img2img(image_url: str, prompt: str, aspect: str = "1:1") -> tuple:
    """Редактирование фото через Nano Banana PRO Edit — возвращает (bytes, url)"""
    if not AIML_KEY:
        raise Exception("AIML_KEY не настроен")

    # Скачать фото и закодировать в base64 (надёжнее чем Telegram URL)
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(image_url)
        r.raise_for_status()
        img_b64 = base64.b64encode(r.content).decode()
        ct = r.headers.get("content-type", "image/jpeg").split(";")[0]
    data_uri = f"data:{ct};base64,{img_b64}"

    # Модель -EDIT использует загруженное фото как основу
    async with httpx.AsyncClient(timeout=180) as client:
        resp = await client.post(
            "https://api.aimlapi.com/v1/images/generations",
            headers={"Authorization": f"Bearer {AIML_KEY}", "Content-Type": "application/json"},
            json={
                "model": "google/nano-banana-pro-edit",
                "prompt": prompt,
                "image_urls": [data_uri],
                "aspect_ratio": aspect,
                "resolution": "1K"
            }
        )
        resp.raise_for_status()
        data = resp.json()

    result_url = ""
    if data.get("images"):
        result_url = data["images"][0].get("url", "")
    elif data.get("data"):
        result_url = data["data"][0].get("url", "")
    if not result_url:
        raise Exception(f"Нет URL в ответе: {list(data.keys())}")

    # Скачать результат
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(result_url)
        r.raise_for_status()
        return r.content, result_url

async def generate_combine(image_urls: list, prompt: str, aspect: str = "1:1") -> tuple:
    """Соединение нескольких фото через Nano Banana PRO Edit — возвращает (bytes, url)"""
    if not AIML_KEY:
        raise Exception("AIML_KEY не настроен")

    # Скачать все фото и закодировать в base64
    data_uris = []
    async with httpx.AsyncClient(timeout=60) as client:
        for u in image_urls[:4]:  # максимум 4 фото
            r = await client.get(u)
            r.raise_for_status()
            b64 = base64.b64encode(r.content).decode()
            ct = r.headers.get("content-type", "image/jpeg").split(";")[0]
            data_uris.append(f"data:{ct};base64,{b64}")

    async with httpx.AsyncClient(timeout=180) as client:
        resp = await client.post(
            "https://api.aimlapi.com/v1/images/generations",
            headers={"Authorization": f"Bearer {AIML_KEY}", "Content-Type": "application/json"},
            json={
                "model": "google/nano-banana-pro-edit",
                "prompt": prompt,
                "image_urls": data_uris,
                "aspect_ratio": aspect,
                "resolution": "1K"
            }
        )
        resp.raise_for_status()
        data = resp.json()

    result_url = ""
    if data.get("images"):
        result_url = data["images"][0].get("url", "")
    elif data.get("data"):
        result_url = data["data"][0].get("url", "")
    if not result_url:
        raise Exception(f"Нет URL в ответе: {list(data.keys())}")

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(result_url)
        r.raise_for_status()
        return r.content, result_url


    if not AIML_KEY:
        raise Exception("AIML_KEY не настроен")
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            "https://api.aimlapi.com/v2/video/generations",
            headers={"Authorization": f"Bearer {AIML_KEY}", "Content-Type": "application/json"},
            json={
                "model": "bytedance/seedance-2-0",
                "prompt": prompt,
                "duration": "5",
                "aspect_ratio": aspect
            }
        )
        resp.raise_for_status()
        data = resp.json()
        task_id = data.get("id")
        if not task_id:
            raise Exception(f"Нет task_id: {list(data.keys())}")

        for _ in range(36):
            await asyncio.sleep(5)
            r = await client.get(
                f"https://api.aimlapi.com/v2/video/generations?generation_id={task_id}",
                headers={"Authorization": f"Bearer {AIML_KEY}"}
            )
            result = r.json()
            status = result.get("status", "")
            if status in ("completed", "succeeded"):
                url = result.get("video", {}).get("url", "")
                if url:
                    return url
                raise Exception("Нет URL видео в ответе")
            elif status in ("failed", "error"):
                raise Exception(f"Seedance failed: {result}")
        raise Exception("Таймаут генерации видео (3 мин)")

async def _try_one_music_model(model: str, prompt: str, extra: dict = None) -> str:
    """Пробует одну модель музыки. Возвращает URL или бросает исключение."""
    payload = {"model": model, "prompt": prompt[:600]}
    if extra:
        payload.update(extra)

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            "https://api.aimlapi.com/v2/generate/audio",
            headers={"Authorization": f"Bearer {AIML_KEY}", "Content-Type": "application/json"},
            json=payload
        )
        resp.raise_for_status()
        data = resp.json()

    if data.get("status") == "completed":
        url = (data.get("audio_file") or {}).get("url", "")
        if url:
            return url

    task_id = data.get("id")
    if not task_id:
        raise Exception(f"нет id: {list(data.keys())}")

    for _ in range(36):
        await asyncio.sleep(5)
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.get(
                    f"https://api.aimlapi.com/v2/generate/audio?generation_id={task_id}",
                    headers={"Authorization": f"Bearer {AIML_KEY}"}
                )
                result = r.json()
        except Exception:
            continue

        status = result.get("status", "")
        if status == "completed":
            url = ""
            if result.get("audio_file"):
                url = result["audio_file"].get("url", "")
            if not url and result.get("audio"):
                url = result["audio"].get("url", "") if isinstance(result["audio"], dict) else result["audio"]
            if not url and result.get("url"):
                url = result["url"]
            if url:
                return url
            raise Exception("нет URL аудио")
        elif status in ("error", "failed"):
            raise Exception(f"{model} failed")

    raise Exception(f"{model} таймаут")


async def generate_music_suno(prompt: str) -> str:
    """Генерация музыки с перебором моделей (если одна падает — пробуем следующую)"""
    if not AIML_KEY:
        raise Exception("AIML_KEY не настроен")

    # Модели по приоритету: (название, доп.параметры)
    models = [
        ("google/lyria2", None),
        ("stable-audio", {"seconds_total": 30}),
        ("minimax/music-2.0", None),
    ]

    last_error = ""
    for model, extra in models:
        try:
            url = await _try_one_music_model(model, prompt, extra)
            if url:
                return url
        except Exception as e:
            last_error = str(e)
            logging.warning(f"Музыка {model} не сработала: {e}, пробую следующую")
            continue

    raise Exception(f"Все модели музыки недоступны. {last_error}")

async def generate_video_kling(prompt: str, aspect: str = "16:9") -> str:
    """Kling через aimlapi.com"""
    if not AIML_KEY:
        raise Exception("AIML_KEY не настроен")
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            "https://api.aimlapi.com/v2/generate/video/kling/generation",
            headers={"Authorization": f"Bearer {AIML_KEY}", "Content-Type": "application/json"},
            json={
                "model": "kling-video/v1.6/standard/text-to-video",
                "prompt": prompt,
                "duration": "5",
                "aspect_ratio": aspect
            }
        )
        resp.raise_for_status()
        data = resp.json()
        task_id = data.get("id") or data.get("generation_id")
        if not task_id:
            raise Exception(f"Нет task_id: {list(data.keys())}")

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

async def generate_video_seedance(prompt: str, aspect: str = "16:9") -> str:
    """Генерация видео по тексту (через надёжный движок Kling)."""
    return await generate_video_kling(prompt, aspect)

async def generate_img2video(image_url: str, prompt: str, aspect: str = "16:9") -> str:
    """Kling img2video — фото в видео через aimlapi.com"""
    if not AIML_KEY:
        raise Exception("AIML_KEY не настроен")
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            "https://api.aimlapi.com/v2/generate/video/kling/generation",
            headers={"Authorization": f"Bearer {AIML_KEY}", "Content-Type": "application/json"},
            json={
                "model": "kling-video/v1.6/standard/image-to-video",
                "image_url": image_url,
                "prompt": prompt,
                "duration": "5",
                "aspect_ratio": aspect
            }
        )
        resp.raise_for_status()
        data = resp.json()
        task_id = data.get("id") or data.get("generation_id")
        if not task_id:
            raise Exception(f"Нет task_id: {list(data.keys())}")

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
                raise Exception(f"Img2Video failed: {result}")
        raise Exception("Таймаут генерации видео")

async def generate_tts(text: str, voice: str = "Nicole") -> bytes:
    """ElevenLabs TTS через aimlapi.com — возвращает аудио байты"""
    if not AIML_KEY:
        raise Exception("AIML_KEY не настроен")
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            "https://api.aimlapi.com/v1/tts",
            headers={"Authorization": f"Bearer {AIML_KEY}", "Content-Type": "application/json"},
            json={
                "model": "elevenlabs/eleven_turbo_v2_5",
                "text": text[:2000],
                "voice": voice
            }
        )
        resp.raise_for_status()
        return resp.content


async def generate_avatar(image_url: str, audio_url: str, model_id: str = "klingai/avatar-standard") -> str:
    """ИИ-аватар (Kling Avatar) через aimlapi — фото + аудио → говорящий аватар (липсинк). Возвращает URL видео."""
    if not AIML_KEY:
        raise Exception("AIML_KEY не настроен")
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            "https://api.aimlapi.com/v2/video/generations",
            headers={"Authorization": f"Bearer {AIML_KEY}", "Content-Type": "application/json"},
            json={"model": model_id, "image_url": image_url, "audio_url": audio_url},
        )
        resp.raise_for_status()
        gen_id = resp.json().get("id")
    if not gen_id:
        raise Exception("Нет id генерации аватара")
    for _ in range(72):
        await asyncio.sleep(5)
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.get(
                f"https://api.aimlapi.com/v2/video/generations?generation_id={gen_id}",
                headers={"Authorization": f"Bearer {AIML_KEY}"},
            )
            r.raise_for_status()
            data = r.json()
        status = data.get("status")
        if status == "completed":
            url = (data.get("video") or {}).get("url")
            if url:
                return url
            raise Exception("Видео готово, но нет URL")
        if status == "error":
            raise Exception(str(data.get("error", "ошибка генерации")))
    raise Exception("Таймаут генерации аватара")


# ══════════════════════════════════════════════════════
#  КЛАВИАТУРЫ
# ══════════════════════════════════════════════════════

def main_kb() -> ReplyKeyboardMarkup:
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
    b.row(KeyboardButton(text="🎓 Обучение"))
    b.row(
        KeyboardButton(text="❓ Помощь"),
        KeyboardButton(text="📕 База знаний"),
    )
    return b.as_markup(resize_keyboard=True)

def text_tools_kb() -> ReplyKeyboardMarkup:
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
    b = ReplyKeyboardBuilder()
    b.row(KeyboardButton(text="🍌 Nano Banana"))
    b.row(KeyboardButton(text="🖼 GPT Image 2"))
    b.row(KeyboardButton(text="🎨 DALL-E 3"))
    b.row(KeyboardButton(text="✏️ Редактировать фото"))
    b.row(KeyboardButton(text="🔗 Соединить фото"))
    b.row(KeyboardButton(text="🏠 В главное меню"))
    return b.as_markup(resize_keyboard=True)

def model_kb() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.row(KeyboardButton(text="🅰 Claude Sonnet — 10 кр."))
    b.row(KeyboardButton(text="🐋 DeepSeek V3 — 5 кр."))
    b.row(KeyboardButton(text="✳️ GPT-4o — 15 кр."))
    b.row(KeyboardButton(text="🏠 В главное меню"))
    return b.as_markup(resize_keyboard=True)

def cancel_kb() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.row(KeyboardButton(text="❌ Отмена"))
    return b.as_markup(resize_keyboard=True, input_field_placeholder="Введи текст или отправь фото…")

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
        b.row(InlineKeyboardButton(
            text=f"{pack['name']}  ·  {pack['rub']}₽ / ⭐️{pack['stars']}",
            callback_data=f"buy_credits_{pid}"
        ))
    return b.as_markup()

def plans_inline_kb():
    b = InlineKeyboardBuilder()
    for pid, p in PLANS.items():
        b.row(InlineKeyboardButton(
            text=f"{p['emoji']} {p['name']}  ·  {p['rub']}₽/мес",
            callback_data=f"buy_plan_{pid}"
        ))
    b.row(InlineKeyboardButton(text="📅 Годовые подписки (−2 месяца)", callback_data="show_annual"))
    return b.as_markup()

def plans_annual_inline_kb():
    b = InlineKeyboardBuilder()
    for pid, p in PLANS_ANNUAL.items():
        b.row(InlineKeyboardButton(
            text=f"{p['emoji']} {p['name']}  ·  {p['rub']}₽/год",
            callback_data=f"buyyear_{pid}"
        ))
    b.row(InlineKeyboardButton(text="📅 Помесячно", callback_data="show_monthly"))
    return b.as_markup()

def pay_method_kb(kind: str, item_id: str):
    """Выбор способа оплаты: Stars или рубли"""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="💳 Картой (рубли)", callback_data=f"payrub_{kind}_{item_id}"))
    b.row(InlineKeyboardButton(text="⭐️ Telegram Stars", callback_data=f"paystars_{kind}_{item_id}"))
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

def audio_kb() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.row(KeyboardButton(text="🎵 Сгенерировать музыку"))
    b.row(KeyboardButton(text="🔊 Озвучить текст"))
    b.row(KeyboardButton(text="🏠 В главное меню"))
    return b.as_markup(resize_keyboard=True)

def video_kb() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.row(KeyboardButton(text="🎬 Создать видео Seedance"))
    b.row(KeyboardButton(text="🎥 Создать видео Kling"))
    b.row(KeyboardButton(text="🖼➡️🎬 Фото в видео"))
    b.row(KeyboardButton(text="🗣 ИИ-аватар (липсинк)"))
    b.row(KeyboardButton(text="🏠 В главное меню"))
    return b.as_markup(resize_keyboard=True)

# ══════════════════════════════════════════════════════
#  РОУТЕР И FSM
# ══════════════════════════════════════════════════════

router = Router()

class State_(StatesGroup):
    choose_model  = State()
    waiting_text  = State()
    waiting_image = State()
    waiting_photo      = State()
    waiting_photo_text = State()
    editing_more       = State()  # продолжение редактирования того же результата
    waiting_combine    = State()  # ожидание фото для соединения
    waiting_video_photo = State()
    waiting_video_photo_aspect = State()
    waiting_video_photo_text = State()
    nalog_phone = State()  # админ: ввод телефона для входа в «Мой налог»
    nalog_code  = State()  # админ: ввод SMS-кода
    course_chat = State()  # чат с ИИ-менеджером курса
    support_chat = State()  # чат с ИИ-поддержкой
    avatar_photo = State()  # ИИ-аватар: ожидание фото
    avatar_audio = State()  # ИИ-аватар: ожидание аудио или текста

user_tool:  dict[int, str] = {}
user_model: dict[int, str] = {}
user_image_model: dict[int, str] = {}
async def get_history(uid: int) -> list:
    rows = await db_all(
        "SELECT role, content FROM chat_history WHERE user_id=? ORDER BY created_at ASC",
        (uid,)
    )
    return [{"role": r["role"], "content": r["content"]} for r in rows]

async def add_to_history(uid: int, role: str, content: str):
    await db_run(
        "INSERT INTO chat_history (user_id, role, content) VALUES (?, ?, ?)",
        (uid, role, content)
    )
    # Держать только последние 30 сообщений
    await db_run(
        "DELETE FROM chat_history WHERE user_id=? AND id NOT IN ("
        "SELECT id FROM chat_history WHERE user_id=? ORDER BY created_at DESC LIMIT 30)",
        (uid, uid)
    )

async def clear_history(uid: int):
    await db_run("DELETE FROM chat_history WHERE user_id=?", (uid,))

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
        text = f"✨ *Добро пожаловать в Vatan AI!*\n\n🎁 Тебе начислено *{bal} кредитов* для старта\n\nВыбери раздел:"
    else:
        bal = await get_balance(message.from_user.id)
        text = f"👋 С возвращением, *{message.from_user.first_name}*!\n\n💎 Кредиты: *{bal}*\n\nВыбери раздел:"

    await message.answer(text, parse_mode="Markdown", reply_markup=main_kb())

    # Пришёл по ссылке с рекламы курса
    if len(args) > 1 and args[1] == "course":
        await show_course_landing(message)

# ══════════════════════════════════════════════════════
#  ОБУЧЕНИЕ / КУРС (ИИ-менеджер продаж)
# ══════════════════════════════════════════════════════

def course_inline_kb():
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text=f"💳 Купить курс — {COURSE['rub']}₽", callback_data="buy_course"))
    b.row(InlineKeyboardButton(text="❓ Задать вопрос менеджеру", callback_data="course_ask"))
    b.row(InlineKeyboardButton(text="🎁 Бесплатный мини-урок", callback_data="course_free"))
    return b.as_markup()

def course_chat_kb() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.row(KeyboardButton(text="🏠 В главное меню"))
    return b.as_markup(resize_keyboard=True)

async def show_course_landing(message: Message):
    text = (
        "🎓 *Курс «Заработок на ИИ-картинках»*\n\n"
        "Научись делать деньги на нейросетях за несколько дней — без навыков дизайна и опыта. Нужен только телефон.\n\n"
        "*Что внутри:*\n"
        "• Обработка фото и портреты\n"
        "• Реклама и карточки товаров\n"
        "• Оживление фото в видео\n"
        "• Как брать платные заказы\n\n"
        f"💎 Цена: *{COURSE['rub']}₽* (или ⭐️{COURSE['stars']})\n"
        "🎁 Бонус: 1 000 кредитов на бота для практики\n\n"
        "Остались вопросы? Жми «Задать вопрос менеджеру» — отвечу 24/7."
    )
    await message.answer(text, parse_mode="Markdown", reply_markup=course_inline_kb())

@router.message(F.text == "🎓 Обучение")
async def course_menu(message: Message, state: FSMContext):
    await state.clear()
    await show_course_landing(message)

@router.callback_query(F.data == "buy_course")
async def cb_buy_course(callback: CallbackQuery):
    await callback.message.answer(
        f"🎓 *{COURSE['name']}*\n\nВыбери способ оплаты:",
        parse_mode="Markdown", reply_markup=pay_method_kb("course", "main")
    )
    await callback.answer()

@router.callback_query(F.data == "course_free")
async def cb_course_free(callback: CallbackQuery):
    await callback.message.answer(
        "🎁 *Бесплатный мини-урок*\n\n"
        "Давай прямо сейчас сделаешь первую ИИ-картинку:\n\n"
        "1️⃣ Зайди в «🎨 Дизайн с ИИ» → «🍌 Nano Banana»\n"
        "2️⃣ Загрузи любое своё фото\n"
        "3️⃣ Напиши, что изменить (например: «сделай студийный портрет»)\n"
        "4️⃣ Получи результат за секунды!\n\n"
        "У тебя уже есть бесплатные кредиты на старте. Попробуй — а потом возвращайся за полным курсом 😉",
        parse_mode="Markdown", reply_markup=course_inline_kb()
    )
    await callback.answer()

@router.callback_query(F.data == "course_ask")
async def cb_course_ask(callback: CallbackQuery, state: FSMContext):
    await state.set_state(State_.course_chat)
    await callback.message.answer(
        "💬 Спрашивай что угодно про курс — отвечу честно. Например: «сколько можно заработать?», «а если не получится?», «как проходит обучение?»\n\n"
        "Чтобы выйти — нажми «🏠 В главное меню».",
        reply_markup=course_chat_kb()
    )
    await callback.answer()

@router.message(State_.course_chat, F.text == "🏠 В главное меню")
async def course_chat_exit(message: Message, state: FSMContext):
    await state.clear()
    bal = await get_balance(message.from_user.id)
    await message.answer(f"🏠 *Главное меню*\n\n💎 Кредиты: *{bal}*", parse_mode="Markdown", reply_markup=main_kb())

@router.message(State_.course_chat)
async def course_chat_answer(message: Message, state: FSMContext):
    data = await state.get_data()
    history = data.get("course_history", [])
    thinking = await message.answer("✍️ ...")
    reply = None
    for mid in ("claude", "gpt4o", "deepseek"):
        try:
            r = await call_text_ai(
                message.text or "", SALES_PROMPT, mid,
                history_msgs=history, timeout_s=30
            )
            if r and not r.startswith("❌"):
                reply = r
                break
        except Exception as e:
            logging.error(f"Sales chat [{mid}] error: {e}")
            continue
    try:
        await thinking.delete()
    except Exception:
        pass
    if not reply:
        await message.answer(
            "Сейчас не могу ответить — попробуй ещё раз через минуту 🙏 "
            "А пока можешь сразу оформить курс кнопкой ниже 👇",
            reply_markup=course_inline_kb()
        )
        return
    # сохранить диалог (последние 12 реплик)
    history = history + [
        {"role": "user", "content": message.text or ""},
        {"role": "assistant", "content": reply},
    ]
    await state.update_data(course_history=history[-12:])
    await message.answer(reply, reply_markup=course_inline_kb())

@router.message(Command("set_course_link"))
async def cmd_set_course_link(message: Message):
    if message.from_user.id != ADMIN_ID: return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        cur = await setting_get("course_link", "не задана")
        await message.answer(f"Текущая ссылка на курс: {cur}\n\nЧтобы задать: /set_course_link https://t.me/+ссылка_на_закрытый_канал")
        return
    await setting_set("course_link", parts[1].strip())
    await message.answer("✅ Ссылка на курс сохранена. После оплаты бот будет присылать её покупателю.")

@router.message(F.text == "🏠 В главное меню")
async def to_main(message: Message, state: FSMContext):
    await state.clear()
    bal = await get_balance(message.from_user.id)
    await message.answer(f"🏠 *Главное меню*\n\n💎 Кредиты: *{bal}*", parse_mode="Markdown", reply_markup=main_kb())

@router.message(F.text == "❌ Отмена")
async def cancel(message: Message, state: FSMContext):
    cur = await state.get_state()
    if cur is None:
        await message.answer("Главное меню 👇", reply_markup=main_kb())
        return
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="✅ Да, отменить", callback_data="do_cancel"))
    b.row(InlineKeyboardButton(text="↩️ Нет, продолжить", callback_data="resume_flow"))
    await message.answer("Точно отменить? Текущий прогресс сбросится.", reply_markup=b.as_markup())

@router.callback_query(F.data == "do_cancel")
async def cb_do_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        combine_buffer.pop(callback.from_user.id, None)
    except Exception:
        pass
    try:
        await callback.message.edit_text("❌ Отменено.")
    except Exception:
        pass
    await callback.message.answer("Главное меню 👇", reply_markup=main_kb())
    await callback.answer()

@router.callback_query(F.data == "resume_flow")
async def cb_resume_flow(callback: CallbackQuery, state: FSMContext):
    try:
        await callback.message.edit_text("👍 Продолжаем — отправь данные дальше.")
    except Exception:
        pass
    await callback.answer("Продолжаем")

@router.message(F.text == "🗑 Очистить историю чата")
async def clear_chat_history(message: Message):
    await clear_history(message.from_user.id)
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

@router.message(F.text == "🎙 Аудио с ИИ")
async def section_audio(message: Message):
    await message.answer(
        "🎙 *Аудио с ИИ*\n\n🎵 Google Lyria 2 — генерация музыки по описанию\n💎 50 кредитов за трек\n\n🔊 ElevenLabs TTS — озвучка текста голосом\n💎 20 кредитов",
        parse_mode="Markdown", reply_markup=audio_kb()
    )

@router.message(F.text == "🎬 Видео будущего")
async def section_video(message: Message):
    await message.answer(
        "🎬 *Видео будущего*\n\n🎬 Seedance 2.0 — видео нового поколения до 5 сек\n💎 150 кредитов\n\n🎥 Kling 1.6 — проверенная классика до 5 сек\n💎 150 кредитов\n\n🖼➡️🎬 Фото в видео — оживи своё фото\n💎 100 кредитов",
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
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="💬 Чат с поддержкой", callback_data="support_chat"))
    await message.answer(
        "❓ *Помощь*\n\n"
        "💡 *GPTs/Claude/Gemini* — текстовые AI инструменты\n"
        "🎨 *Дизайн с ИИ* — картинки, обработка и соединение фото\n"
        "🎙 *Аудио с ИИ* — музыка и озвучка голосом\n"
        "🎬 *Видео будущего* — видео, фото в видео, говорящие аватары\n"
        "🎓 *Обучение* — курс по заработку на ИИ\n\n"
        "💎 Кредиты списываются за каждый запрос (на старте дают бесплатные)\n"
        "💳 Пополнить: Профиль → Купить кредиты (карта или Stars)\n"
        "🔗 Рефералы — приглашай и зарабатывай\n\n"
        "Есть вопрос? Нажми кнопку ниже — отвечу 👇",
        parse_mode="Markdown", reply_markup=b.as_markup()
    )

def support_chat_kb() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.row(KeyboardButton(text="🏠 В главное меню"))
    return b.as_markup(resize_keyboard=True)

@router.callback_query(F.data == "support_chat")
async def cb_support_chat(callback: CallbackQuery, state: FSMContext):
    await state.set_state(State_.support_chat)
    await callback.message.answer(
        "💬 Я — поддержка Vatan AI. Опиши свой вопрос или проблему — помогу разобраться.\n\n"
        "Например: «как пополнить кредиты?», «не пришло видео», «как редактировать фото?»\n\n"
        "Чтобы выйти — нажми «🏠 В главное меню».",
        reply_markup=support_chat_kb()
    )
    await callback.answer()

@router.message(State_.support_chat, F.text == "🏠 В главное меню")
async def support_chat_exit(message: Message, state: FSMContext):
    await state.clear()
    bal = await get_balance(message.from_user.id)
    await message.answer(f"🏠 *Главное меню*\n\n💎 Кредиты: *{bal}*", parse_mode="Markdown", reply_markup=main_kb())

@router.message(State_.support_chat)
async def support_chat_answer(message: Message, state: FSMContext):
    data = await state.get_data()
    history = data.get("support_history", [])
    thinking = await message.answer("✍️ ...")
    reply = None
    for mid in ("claude", "gpt4o", "deepseek"):
        try:
            r = await call_text_ai(message.text or "", SUPPORT_PROMPT, mid, history_msgs=history, timeout_s=30)
            if r and not r.startswith("❌"):
                reply = r
                break
        except Exception as e:
            logging.error(f"Support chat [{mid}] error: {e}")
            continue
    try:
        await thinking.delete()
    except Exception:
        pass
    if not reply:
        await message.answer(
            "Сейчас не могу ответить — попробуй ещё раз через минуту 🙏\n"
            "Если вопрос срочный — напиши администратору.",
            reply_markup=support_chat_kb()
        )
        return
    history = history + [
        {"role": "user", "content": message.text or ""},
        {"role": "assistant", "content": reply},
    ]
    await state.update_data(support_history=history[-12:])
    await message.answer(reply, reply_markup=support_chat_kb())

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
        "💎 *Купить кредиты*\n\nОплата картой (рубли) или Telegram Stars.\nКредиты зачисляются мгновенно и не сгорают.\n\nВыбери пакет:",
        parse_mode="Markdown", reply_markup=credits_pack_kb()
    )

@router.message(F.text == "👑 Подписки")
async def buy_plans(message: Message):
    user = await get_user(message.from_user.id)
    plan = user["plan"] if user else "free"

    text = (
        "👑 *Подписки Vatan AI*\n"
        "_Чем выше тариф — тем дешевле каждая генерация._\n\n"

        f"{'✅ ' if plan=='basic' else ''}⭐️ *Basic — 390₽/мес*\n"
        "• 2 000 кредитов\n"
        "• Хватит на ~16 фото или 5 видео\n"
        "• Все функции бота\n\n"

        f"{'✅ ' if plan=='pro' else ''}👑 *Pro — 1 090₽/мес*  🔥 выгодно\n"
        "• 4 500 кредитов\n"
        "• 🏷 Скидка *25%* на фото и картинки\n"
        "• Хватит на ~50 фото или 11 видео\n"
        "• Все функции бота\n\n"

        f"{'✅ ' if plan=='premium' else ''}💎 *Premium — 2 290₽/мес*  ⭐️ максимум\n"
        "• 9 000 кредитов\n"
        "• ♾ *Безлимит на AI-чат* (пиши сколько хочешь)\n"
        "• 🏷 Скидка *50%* на фото и картинки\n"
        "• Хватит на ~150 фото или 22 видео\n"
        "• Приоритетная генерация\n\n"

        "💡 _Кредиты не сгорают. Скидки применяются автоматически._"
    )
    await message.answer(text, parse_mode="Markdown", reply_markup=plans_inline_kb())

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
#  ТЕКСТОВЫЕ ИНСТРУМЕНТЫ
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

@router.message(State_.waiting_text, F.photo)
async def process_text_with_photo(message: Message, state: FSMContext):
    """Обработка фото в текстовом чате"""
    await process_text(message, state)

@router.message(State_.choose_model, F.photo)
async def photo_in_model_selection(message: Message, state: FSMContext):
    """Если прислали фото когда нужно выбрать модель"""
    # Сохранить фото для последующего использования
    photo = message.photo[-1]
    file = await message.bot.get_file(photo.file_id)
    file_url = f"https://api.telegram.org/file/bot{message.bot.token}/{file.file_path}"
    await state.update_data(pending_photo=file_url, pending_caption=message.caption or "")
    await message.answer(
        "📸 Фото получено! Теперь выбери AI модель:",
        reply_markup=model_kb()
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

    # Если было отложенное фото — сразу обработать
    pending_photo = (await state.get_data()).get("pending_photo")
    pending_caption = (await state.get_data()).get("pending_caption", "")
    if pending_photo and tool_id == "chat":
        await state.update_data(tool=tool_id, model=model_id, cost=total_cost)
        await state.set_state(State_.waiting_text)
        # Создать фиктивное сообщение не получится — просто подсказать
        await state.update_data(pending_photo=None)
        await message.answer(
            f"{model_info['emoji']} *{model_info['name']}*  ·  💎 {total_cost} кредитов\n\n"
            f"Фото сохранено! Теперь отправь его снова вместе с вопросом:",
            parse_mode="Markdown", reply_markup=cancel_kb()
        )
    else:
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

    # Получить текст и фото если есть
    user_text = message.text or message.caption or ""
    image_url = None
    if message.photo:
        photo = message.photo[-1]
        file = await message.bot.get_file(photo.file_id)
        image_url = f"https://api.telegram.org/file/bot{message.bot.token}/{file.file_path}"
        if not user_text:
            user_text = "Опиши что на этом изображении"

    if not user_text and not image_url:
        await message.answer("Введи текст или отправь фото:")
        return

    ok = await use_credits(message.from_user.id, tool_id, cost)
    if not ok:
        await message.answer("❌ Недостаточно кредитов.", reply_markup=profile_kb())
        await state.clear(); return

    await state.clear()
    thinking = await message.answer("⏳ Генерирую...", reply_markup=ReplyKeyboardRemove())

    try:
        system = SYSTEM_PROMPTS.get(tool_id, SYSTEM_PROMPTS["chat"])
        use_history = (tool_id == "chat")
        result = await call_text_ai(user_text, system, model_id, uid=message.from_user.id, use_history=use_history, image_url=image_url)
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

        # Если это чат — остаться в состоянии для продолжения разговора
        if tool_id == "chat":
            await state.set_state(State_.waiting_text)
            await state.update_data(tool=tool_id, model=model_id, cost=cost)
            await message.answer(
                "💬 Продолжай писать или нажми кнопку ниже:",
                reply_markup=cancel_kb()
            )
        else:
            await message.answer("Что дальше?", reply_markup=text_tools_kb())

    except asyncio.TimeoutError:
        await add_credits(message.from_user.id, cost, "bonus", "Возврат: таймаут")
        try:
            await thinking.edit_text("⏱ Время вышло (15 сек). Кредиты возвращены. Попробуй ещё раз.")
        except Exception:
            await message.answer("⏱ Время вышло (15 сек). Кредиты возвращены. Попробуй ещё раз.")
        if tool_id == "chat":
            await state.set_state(State_.waiting_text)
            await state.update_data(tool=tool_id, model=model_id, cost=cost)
            await message.answer("Попробуй ещё раз:", reply_markup=cancel_kb())
        else:
            await message.answer("Выбери инструмент:", reply_markup=text_tools_kb())
        logging.error(f"Text AI timeout [{tool_id}/{model_id}]")

    except Exception as e:
        await add_credits(message.from_user.id, cost, "bonus", "Возврат: ошибка AI")
        try:
            await thinking.edit_text(f"⚠️ Ошибка AI. Кредиты возвращены.\n\n{str(e)[:100]}")
        except Exception:
            await message.answer("⚠️ Ошибка AI. Кредиты возвращены.")
        if tool_id == "chat":
            await state.set_state(State_.waiting_text)
            await state.update_data(tool=tool_id, model=model_id, cost=cost)
            await message.answer("Попробуй ещё раз:", reply_markup=cancel_kb())
        else:
            await message.answer("Попробуй ещё раз:", reply_markup=text_tools_kb())
        logging.error(f"Text AI error [{tool_id}/{model_id}]: {e}")

# ══════════════════════════════════════════════════════
#  ГЕНЕРАЦИЯ КАРТИНОК
# ══════════════════════════════════════════════════════

def image_mode_kb() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.row(KeyboardButton(text="✏️ С нуля по описанию"))
    b.row(KeyboardButton(text="🖼 На основе моего фото"))
    b.row(KeyboardButton(text="❌ Отмена"))
    return b.as_markup(resize_keyboard=True)

def aspect_kb() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.row(KeyboardButton(text="⬛ 1:1 Квадрат"))
    b.row(KeyboardButton(text="📱 9:16 Вертикальное"), KeyboardButton(text="🖥 16:9 Горизонтальное"))
    b.row(KeyboardButton(text="🖼 4:3"), KeyboardButton(text="📷 3:4"))
    b.row(KeyboardButton(text="❌ Отмена"))
    return b.as_markup(resize_keyboard=True)

ASPECT_MAP = {
    "⬛ 1:1 Квадрат": "1:1",
    "📱 9:16 Вертикальное": "9:16",
    "🖥 16:9 Горизонтальное": "16:9",
    "🖼 4:3": "4:3",
    "📷 3:4": "3:4",
}

@router.message(F.text.in_({"🖼 GPT Image 2", "🎨 DALL-E 3", "🍌 Nano Banana"}))
async def image_tool_selected(message: Message, state: FSMContext):
    if "Nano Banana" in message.text:
        cost = 110
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
    await state.update_data(image_model=model, cost=cost)
    await state.set_state(State_.waiting_image)

    await message.answer(
        f"*{message.text}*  ·  💎 {cost} кредитов\n\n"
        f"Выбери режим:",
        parse_mode="Markdown", reply_markup=image_mode_kb()
    )

@router.message(State_.waiting_image, F.text == "✏️ С нуля по описанию")
async def image_from_scratch(message: Message, state: FSMContext):
    await state.update_data(base_photo=None)
    await message.answer(
        "Выбери формат изображения:",
        reply_markup=aspect_kb()
    )

def video_mode_kb() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.row(KeyboardButton(text="📝 По тексту"))
    b.row(KeyboardButton(text="🖼 На основе фото"))
    b.row(KeyboardButton(text="❌ Отмена"))
    return b.as_markup(resize_keyboard=True)

@router.message(State_.waiting_image, F.text.in_(ASPECT_MAP.keys()))
async def image_aspect_selected(message: Message, state: FSMContext):
    aspect = ASPECT_MAP[message.text]
    await state.update_data(aspect=aspect)
    data = await state.get_data()
    model = data.get("image_model", "dalle")
    if model in ("video", "kling"):
        await message.answer(
            f"Формат: *{aspect}* ✅\n\n"
            "Как создать видео?",
            parse_mode="Markdown", reply_markup=video_mode_kb()
        )
    else:
        await message.answer(
            f"Формат: *{aspect}* ✅\n\n"
            "Теперь опиши картинку которую хочешь создать:\n\n"
            "Пример: *красивый закат над горами, фотореализм, 4K*",
            parse_mode="Markdown", reply_markup=cancel_kb()
        )

@router.message(State_.waiting_image, F.text == "📝 По тексту")
async def video_mode_text(message: Message, state: FSMContext):
    await state.update_data(waiting_base_photo=False, base_photo=None)
    await message.answer(
        "Опиши видео которое хочешь создать:\n\n"
        "Пример: *закат над морем, волны, кинематографичная съёмка*",
        parse_mode="Markdown", reply_markup=cancel_kb()
    )

@router.message(State_.waiting_image, F.text == "🖼 На основе фото")
async def video_mode_photo(message: Message, state: FSMContext):
    await state.update_data(waiting_base_photo=True)
    await message.answer(
        "📸 Отправь фото которое хочешь оживить в видео:",
        reply_markup=cancel_kb()
    )

@router.message(State_.waiting_image, F.text == "🖼 На основе моего фото")
async def image_from_photo_prompt(message: Message, state: FSMContext):
    await state.update_data(waiting_base_photo=True)
    await message.answer(
        "📸 Отправь своё фото которое хочешь использовать как основу:",
        reply_markup=cancel_kb()
    )

@router.message(State_.waiting_image, F.photo)
async def image_base_photo_received(message: Message, state: FSMContext):
    data = await state.get_data()
    if data.get("waiting_base_photo"):
        photo = message.photo[-1]
        file = await message.bot.get_file(photo.file_id)
        file_url = f"https://api.telegram.org/file/bot{message.bot.token}/{file.file_path}"
        await state.update_data(base_photo=file_url, waiting_base_photo=False)
        model = data.get("image_model", "dalle")
        if model in ("video", "kling"):
            await message.answer(
                "✅ Фото получено!\n\n"
                "Теперь опиши что должно происходить в видео:\n\n"
                "Примеры:\n"
                "• *плавное движение камеры вперёд*\n"
                "• *волосы развеваются на ветру*\n"
                "• *облака медленно плывут*",
                parse_mode="Markdown", reply_markup=cancel_kb()
            )
        else:
            await message.answer(
                "✅ Фото получено!\n\n"
                "Теперь опиши что хочешь изменить или создать на основе этого фото:\n\n"
                "Примеры:\n"
                "• *сделай фон космическим*\n"
                "• *измени стиль на аниме*\n"
                "• *добавь снег*",
                parse_mode="Markdown", reply_markup=cancel_kb()
            )

@router.message(State_.waiting_image)
async def process_image(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=design_kb()); return

    # Игнорировать кнопки режима (они обрабатываются выше)
    if message.text in ("✏️ С нуля по описанию", "🖼 На основе моего фото"):
        return

    data  = await state.get_data()
    model = data.get("image_model", "dalle")
    cost  = data.get("cost", 50)
    base_photo = data.get("base_photo")
    aspect = data.get("aspect", "16:9" if model in ("video", "kling") else "1:1")

    # Если ждём фото — пропустить текст
    if data.get("waiting_base_photo") and not message.photo:
        await message.answer("📸 Пожалуйста отправь фото:")
        return

    ok = await use_credits(message.from_user.id, f"image_{model}", cost)
    if not ok:
        await message.answer("❌ Недостаточно кредитов.", reply_markup=profile_kb())
        await state.clear(); return

    await state.clear()
    # Для фоновых задач (музыка/видео) оставляем меню чтобы можно было запускать другое
    if model in ("music", "kling", "video"):
        initial_text = "⏳ Запускаю генерацию..."
        thinking = await message.answer(initial_text, reply_markup=main_kb())
    else:
        thinking = await message.answer("🎨 Генерирую картинку... (~15-30 сек)", reply_markup=ReplyKeyboardRemove())

    try:
        bal = await get_balance(message.from_user.id)

        if model == "music":
            try:
                await thinking.edit_text(
                    "🎵 *Генерирую музыку...*\n\n"
                    "⏱ Это займёт ~2-3 минуты\n"
                    "✅ Можешь пользоваться ботом — результат придёт автоматически!"
                )
            except Exception:
                pass

            async def music_task():
                try:
                    url = await generate_music_suno(message.text)
                    # Скачиваем аудио сами (Telegram не может качать с CDN aimlapi)
                    async with httpx.AsyncClient(timeout=120) as client:
                        ar = await client.get(url)
                        ar.raise_for_status()
                        audio_bytes = ar.content
                    # Определяем расширение
                    ext = "wav" if url.lower().endswith(".wav") else "mp3"
                    b = await get_balance(message.from_user.id)
                    await message.answer_audio(
                        BufferedInputFile(audio_bytes, filename=f"track.{ext}"),
                        caption=f"🎵 *Музыка готова!*\n\n💎 Потрачено: *{cost} кр.* · Остаток: *{b} кр.*",
                        parse_mode="Markdown"
                    )
                    await message.answer("Что дальше?", reply_markup=audio_kb())
                except Exception as e:
                    await add_credits(message.from_user.id, cost, "bonus", "Возврат: ошибка музыки")
                    await message.answer(f"⚠️ Ошибка генерации музыки. Кредиты возвращены.\n{str(e)[:100]}", reply_markup=audio_kb())
                    logging.error(f"Music task error: {e}")
                finally:
                    try:
                        await thinking.delete()
                    except Exception:
                        pass

            asyncio.create_task(music_task())
            return

        elif model == "kling":
            _kling_base = base_photo
            _kling_prompt = message.text
            _kling_aspect = aspect
            try:
                await thinking.edit_text(
                    "🎥 *Генерирую видео Kling...*\n\n"
                    "⏱ Это займёт ~2-3 минуты\n"
                    "✅ Можешь пользоваться ботом — результат придёт автоматически!"
                )
            except Exception:
                pass

            async def kling_task():
                try:
                    if _kling_base:
                        url = await generate_img2video(_kling_base, _kling_prompt)
                    else:
                        url = await generate_video_kling(_kling_prompt, _kling_aspect)
                    async with httpx.AsyncClient(timeout=180) as client:
                        vr = await client.get(url)
                        vr.raise_for_status()
                        video_bytes = vr.content
                    b = await get_balance(message.from_user.id)
                    await message.answer_video(
                        BufferedInputFile(video_bytes, filename="video.mp4"),
                        caption=f"🎥 *Kling 1.6*\n\n💎 Потрачено: *{cost} кр.* · Остаток: *{b} кр.*",
                        parse_mode="Markdown"
                    )
                    await message.answer("Что дальше?", reply_markup=video_kb())
                except Exception as e:
                    await add_credits(message.from_user.id, cost, "bonus", "Возврат: ошибка видео")
                    await message.answer(f"⚠️ Ошибка генерации видео. Кредиты возвращены.\n{str(e)[:100]}", reply_markup=video_kb())
                    logging.error(f"Kling task error: {e}")
                finally:
                    try:
                        await thinking.delete()
                    except Exception:
                        pass

            asyncio.create_task(kling_task())
            return

        elif model == "tts":
            try:
                await thinking.edit_text("🔊 Озвучиваю текст...")
            except Exception:
                pass
            audio_bytes = await generate_tts(message.text)
            try:
                await thinking.delete()
            except Exception:
                pass
            await message.answer_voice(
                BufferedInputFile(audio_bytes, filename="speech.mp3"),
                caption=f"🔊 *ElevenLabs TTS*\n\n💎 Потрачено: *{cost} кр.* · Остаток: *{bal} кр.*",
                parse_mode="Markdown"
            )
            await message.answer("Что дальше?", reply_markup=audio_kb())

        elif model == "video":
            try:
                await thinking.edit_text(
                    "🎬 *Генерирую видео Seedance...*\n\n"
                    "⏱ Это займёт ~1-3 минуты\n"
                    "✅ Можешь пользоваться ботом — результат придёт автоматически!"
                )
            except Exception:
                pass
            _prompt = message.text
            _aspect = aspect
            _seed_base = base_photo

            async def seedance_task():
                try:
                    if _seed_base:
                        url = await generate_img2video(_seed_base, _prompt)
                    else:
                        url = await generate_video_seedance(_prompt, _aspect)
                    async with httpx.AsyncClient(timeout=180) as client:
                        vr = await client.get(url)
                        vr.raise_for_status()
                        video_bytes = vr.content
                    b = await get_balance(message.from_user.id)
                    await message.answer_video(
                        BufferedInputFile(video_bytes, filename="video.mp4"),
                        caption=f"🎬 *Seedance 2.0*\n\n💎 Потрачено: *{cost} кр.* · Остаток: *{b} кр.*",
                        parse_mode="Markdown"
                    )
                    await message.answer("Что дальше?", reply_markup=video_kb())
                except Exception as e:
                    await add_credits(message.from_user.id, cost, "bonus", "Возврат: ошибка видео")
                    await message.answer(f"⚠️ Ошибка генерации видео. Кредиты возвращены.\n{str(e)[:100]}", reply_markup=video_kb())
                    logging.error(f"Seedance task error: {e}")
                finally:
                    try:
                        await thinking.delete()
                    except Exception:
                        pass

            asyncio.create_task(seedance_task())
            return

        else:
            prompt = message.text or ""
            aspect = data.get("aspect", "1:1")
            if base_photo:
                # Использовать img2img с базовым фото
                img_bytes, _ = await generate_img2img(base_photo, prompt)
            elif model == "nano":
                img_bytes = await generate_nano_banana(prompt, aspect)
            elif model == "gpt":
                img_bytes = await generate_image_gpt(prompt, aspect)
            else:
                img_bytes = await generate_image_dalle(prompt, aspect)

            model_name = {"nano": "🍌 Nano Banana", "gpt": "GPT Image 2", "dalle": "DALL-E 3"}.get(model, model)
            try:
                await thinking.delete()
            except Exception:
                pass
            await message.answer_photo(
                BufferedInputFile(img_bytes, filename="image.png"),
                caption=f"🎨 *{model_name}*  ·  Формат {aspect}\n\n💎 Потрачено: *{cost} кр.* · Остаток: *{bal} кр.*",
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
        await message.answer(f"⚠️ Ошибка. Кредиты возвращены.\n{str(e)[:150]}")
        kb = audio_kb() if model == "music" else (video_kb() if model == "video" else design_kb())
        await message.answer("Попробуй снова:", reply_markup=kb)
        logging.error(f"Media generation error [{model}]: {e}")

# ══════════════════════════════════════════════════════
#  МУЗЫКА И ВИДЕО
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
        f"🎵 *Google Lyria 2*  ·  💎 {cost} кредитов\n\n"
        f"Опиши музыку которую хочешь создать:\n\n"
        f"Пример: *энергичный рок трек для мотивации, гитара и барабаны*",
        parse_mode="Markdown", reply_markup=cancel_kb()
    )

@router.message(F.text == "🎬 Создать видео Seedance")
async def video_generate(message: Message, state: FSMContext):
    cost = 400
    bal  = await get_balance(message.from_user.id)
    if bal < cost:
        await message.answer(f"❌ Нужно *{cost} кр.* · У тебя *{bal} кр.*", parse_mode="Markdown", reply_markup=profile_kb())
        return
    await state.set_state(State_.waiting_image)
    await state.update_data(image_model="video", cost=cost)
    await message.answer(
        f"🎬 *Seedance 2.0*  ·  💎 {cost} кредитов\n\n"
        f"Выбери формат видео:",
        parse_mode="Markdown", reply_markup=aspect_kb()
    )
@router.message(F.text == "🔊 Озвучить текст")
async def tts_start(message: Message, state: FSMContext):
    cost = 20
    bal  = await get_balance(message.from_user.id)
    if bal < cost:
        await message.answer(f"❌ Нужно *{cost} кр.* · У тебя *{bal} кр.*", parse_mode="Markdown", reply_markup=profile_kb())
        return
    await state.set_state(State_.waiting_image)
    await state.update_data(image_model="tts", cost=cost)
    await message.answer(
        f"🔊 *ElevenLabs TTS*  ·  💎 {cost} кредитов\n\n"
        f"Введи текст который хочешь озвучить:\n\n"
        f"Пример: *Привет! Добро пожаловать в Vatan AI*",
        parse_mode="Markdown", reply_markup=cancel_kb()
    )
@router.message(F.text == "🎥 Создать видео Kling")
async def kling_generate(message: Message, state: FSMContext):
    cost = 400
    bal  = await get_balance(message.from_user.id)
    if bal < cost:
        await message.answer(f"❌ Нужно *{cost} кр.* · У тебя *{bal} кр.*", parse_mode="Markdown", reply_markup=profile_kb())
        return
    await state.set_state(State_.waiting_image)
    await state.update_data(image_model="kling", cost=cost)
    await message.answer(
        f"🎥 *Kling 1.6*  ·  💎 {cost} кредитов\n\n"
        f"Выбери формат видео:",
        parse_mode="Markdown", reply_markup=aspect_kb()
    )



# ══════════════════════════════════════════════════════
#  РЕДАКТИРОВАНИЕ ФОТО
# ══════════════════════════════════════════════════════

user_photo_urls: dict[int, str] = {}
user_last_edited: dict[int, str] = {}  # последний результат редактирования (URL)
user_video_photo_urls: dict[int, str] = {}

@router.message(F.text == "✏️ Редактировать фото")
async def img2img_start(message: Message, state: FSMContext):
    cost = 120
    bal = await get_balance(message.from_user.id)
    if bal < cost:
        await message.answer(f"❌ Нужно *{cost} кр.* · У тебя *{bal} кр.*", parse_mode="Markdown", reply_markup=profile_kb())
        return
    await state.set_state(State_.waiting_photo)
    await state.update_data(cost=cost)
    await message.answer(
        "✏️ *Редактировать фото*  ·  💎 70 кредитов\n\n"
        "1️⃣ Отправь фото которое хочешь изменить:",
        parse_mode="Markdown", reply_markup=cancel_kb()
    )

@router.message(State_.waiting_photo, F.photo)
async def img2img_photo_received(message: Message, state: FSMContext):
    photo = message.photo[-1]
    file = await message.bot.get_file(photo.file_id)
    file_url = f"https://api.telegram.org/file/bot{message.bot.token}/{file.file_path}"
    user_photo_urls[message.from_user.id] = file_url

    # Если фото пришло с подписью — сразу редактируем
    if message.caption:
        await state.set_state(State_.waiting_photo_text)
        await _do_img2img(message, state, file_url, message.caption)
        return

    # Спросить формат
    await state.set_state(State_.waiting_photo_text)
    await state.update_data(need_aspect=True)
    await message.answer(
        "✅ Фото получено!\n\nВыбери формат результата:",
        reply_markup=aspect_kb()
    )

@router.message(State_.waiting_photo_text, F.text.in_(ASPECT_MAP.keys()))
async def img2img_aspect_selected(message: Message, state: FSMContext):
    aspect = ASPECT_MAP[message.text]
    await state.update_data(aspect=aspect, need_aspect=False)
    await message.answer(
        f"Формат: *{aspect}* ✅\n\n"
        "Теперь опиши что хочешь изменить:\n\n"
        "Примеры:\n"
        "• *сделай фон розовым*\n"
        "• *добавь снег*\n"
        "• *измени стиль на аниме*\n"
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
    if data.get("need_aspect"):
        await message.answer("👆 Сначала выбери формат кнопкой выше:")
        return

    image_url = user_photo_urls.get(message.from_user.id)
    if not image_url:
        await message.answer("❌ Фото не найдено. Начни заново.", reply_markup=design_kb())
        await state.clear()
        return

    await _do_img2img(message, state, image_url, message.text)


async def _do_img2img(message: Message, state: FSMContext, image_url: str, prompt_text: str):
    """Общая логика редактирования фото"""
    data = await state.get_data()
    cost = data.get("cost", 120)
    aspect = data.get("aspect", "1:1")

    ok = await use_credits(message.from_user.id, "img2img", cost)
    if not ok:
        await message.answer("❌ Недостаточно кредитов.", reply_markup=profile_kb())
        await state.clear()
        return

    await state.clear()
    thinking = await message.answer("✏️ Редактирую фото... (~15-30 сек)", reply_markup=ReplyKeyboardRemove())

    try:
        img_bytes, result_url = await generate_img2img(image_url, prompt_text, aspect)
        bal = await get_balance(message.from_user.id)
        try:
            await thinking.delete()
        except Exception:
            pass
        # Отправляем фото отдельно (без длинной подписи чтобы точно отобразилось)
        await message.answer_photo(
            BufferedInputFile(img_bytes, filename="edited.png"),
            caption=f"✅ Готово! Качество 2K · NanoBanana PRO"
        )
        # Инфо и ссылка отдельным сообщением
        await message.answer(
            f"📌 Запрос: _{prompt_text}_\n\n"
            f"💎 Потрачено: *{cost} кр.* · Остаток: *{bal} кр.*\n\n"
            f"[📥 Скачать в высоком качестве]({result_url})",
            parse_mode="Markdown",
            disable_web_page_preview=False
        )
        # Сохраняем результат для продолжения редактирования
        user_last_edited[message.from_user.id] = result_url
        # Инфо и ссылка отдельным сообщением
        await message.answer(
            f"📌 Запрос: _{prompt_text}_\n\n"
            f"💎 Потрачено: *{cost} кр.* · Остаток: *{bal} кр.*\n\n"
            f"[📥 Скачать в высоком качестве]({result_url})",
            parse_mode="Markdown",
            disable_web_page_preview=False
        )
        # Режим продолжения: можно менять этот же результат текстом
        await state.set_state(State_.editing_more)
        await state.update_data(cost=cost, aspect=aspect)
        await message.answer(
            "✏️ *Что дальше?*\n\n"
            "• Напиши новое изменение — применю к *этому же* результату\n"
            "• Или отправь *новое фото* чтобы начать заново\n"
            "• ❌ Отмена — выйти",
            parse_mode="Markdown",
            reply_markup=cancel_kb()
        )
        await log_request(message.from_user.id, "img2img", "nano-banana-pro", cost)

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
            await thinking.edit_text(f"⚠️ Ошибка. Кредиты возвращены.\n{str(e)[:100]}")
        except Exception:
            await message.answer("⚠️ Ошибка. Кредиты возвращены.")
        await message.answer("Попробуй снова:", reply_markup=design_kb())
        logging.error(f"img2img error: {e}")


@router.message(State_.editing_more, F.photo)
async def editing_more_new_photo(message: Message, state: FSMContext):
    """В режиме продолжения пришло новое фото — начинаем заново с него"""
    photo = message.photo[-1]
    file = await message.bot.get_file(photo.file_id)
    file_url = f"https://api.telegram.org/file/bot{message.bot.token}/{file.file_path}"
    user_photo_urls[message.from_user.id] = file_url

    if message.caption:
        # Фото с подписью — сразу редактируем
        await _do_img2img(message, state, file_url, message.caption)
        return

    await state.set_state(State_.waiting_photo_text)
    await message.answer(
        "✅ Новое фото получено!\n\nОпиши что изменить:",
        reply_markup=cancel_kb()
    )


@router.message(State_.editing_more, F.text)
async def editing_more_text(message: Message, state: FSMContext):
    """В режиме продолжения пришёл текст — применяем к последнему результату"""
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Готово! Возвращаю в меню.", reply_markup=design_kb())
        return

    last_url = user_last_edited.get(message.from_user.id)
    if not last_url:
        await message.answer("❌ Нет предыдущего результата. Отправь фото заново.", reply_markup=design_kb())
        await state.clear()
        return

    # Редактируем последний результат новым промтом
    await _do_img2img(message, state, last_url, message.text)

@router.message(F.text == "🖼➡️🎬 Фото в видео")
async def img2video_video_start(message: Message, state: FSMContext):
    cost = 100
    bal = await get_balance(message.from_user.id)
    if bal < cost:
        await message.answer(f"❌ Нужно *{cost} кр.* · У тебя *{bal} кр.*", parse_mode="Markdown", reply_markup=profile_kb())
        return
    await state.set_state(State_.waiting_video_photo)
    await state.update_data(cost=cost)
    await message.answer(
        "🖼➡️🎬 *Фото в видео*  ·  💎 100 кредитов\n\n"
        "1️⃣ Отправь фото которое хочешь оживить:",
        parse_mode="Markdown", reply_markup=cancel_kb()
    )

@router.message(State_.waiting_video_photo, F.photo)
async def img2video_photo_received(message: Message, state: FSMContext):
    photo = message.photo[-1]
    file = await message.bot.get_file(photo.file_id)
    file_url = f"https://api.telegram.org/file/bot{message.bot.token}/{file.file_path}"
    user_video_photo_urls[message.from_user.id] = file_url
    await state.set_state(State_.waiting_video_photo_aspect)
    b = ReplyKeyboardBuilder()
    b.row(KeyboardButton(text="📱 9:16 Вертикальное"))
    b.row(KeyboardButton(text="🖥 16:9 Горизонтальное"))
    b.row(KeyboardButton(text="📷 3:4"))
    b.row(KeyboardButton(text="❌ Отмена"))
    await message.answer(
        "✅ Фото получено!\n\n"
        "2️⃣ Выбери формат видео:",
        reply_markup=b.as_markup(resize_keyboard=True)
    )

VIDEO_PHOTO_ASPECTS = {
    "📱 9:16 Вертикальное": "9:16",
    "🖥 16:9 Горизонтальное": "16:9",
    "📷 3:4": "3:4",
}

@router.message(State_.waiting_video_photo_aspect, F.text.in_(VIDEO_PHOTO_ASPECTS.keys()))
async def img2video_aspect_received(message: Message, state: FSMContext):
    aspect = VIDEO_PHOTO_ASPECTS[message.text]
    await state.update_data(video_aspect=aspect)
    await state.set_state(State_.waiting_video_photo_text)
    await message.answer(
        f"Формат: *{aspect}* ✅\n\n"
        "3️⃣ Опиши что должно происходить в видео:\n\n"
        "Примеры:\n"
        "• *плавное движение камеры вперёд*\n"
        "• *волосы развеваются на ветру*\n"
        "• *облака медленно плывут*",
        parse_mode="Markdown", reply_markup=cancel_kb()
    )

@router.message(State_.waiting_video_photo_aspect, F.text != "❌ Отмена")
async def img2video_aspect_invalid(message: Message):
    await message.answer("📐 Выбери формат кнопкой: 9:16, 16:9 или 3:4")

@router.message(State_.waiting_video_photo, F.text != "❌ Отмена")
async def img2video_no_photo(message: Message):
    await message.answer("📸 Пожалуйста отправь фото:")

@router.message(State_.waiting_video_photo_text)
async def img2video_video_process(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=video_kb())
        return

    data = await state.get_data()
    cost = data.get("cost", 100)
    aspect = data.get("video_aspect", "16:9")
    image_url = user_video_photo_urls.get(message.from_user.id)

    if not image_url:
        await message.answer("❌ Фото не найдено. Начни заново.", reply_markup=video_kb())
        await state.clear()
        return

    ok = await use_credits(message.from_user.id, "img2video", cost)
    if not ok:
        await message.answer("❌ Недостаточно кредитов.", reply_markup=profile_kb())
        await state.clear()
        return

    await state.clear()
    thinking = await message.answer(
        "🖼➡️🎬 *Генерирую видео из фото...*\n\n"
        "⏱ Это займёт ~2-3 минуты\n"
        "✅ Можешь пользоваться ботом — результат придёт автоматически!",
        parse_mode="Markdown", reply_markup=main_kb()
    )

    prompt = message.text
    uid = message.from_user.id

    async def img2video_task():
        try:
            url = await generate_img2video(image_url, prompt, aspect)
            async with httpx.AsyncClient(timeout=180) as client:
                vr = await client.get(url)
                vr.raise_for_status()
                video_bytes = vr.content
            bal = await get_balance(uid)
            await message.answer_video(
                BufferedInputFile(video_bytes, filename="video.mp4"),
                caption=f"🖼➡️🎬 *Фото в видео*\n\n💎 Потрачено: *{cost} кр.* · Остаток: *{bal} кр.*",
                parse_mode="Markdown"
            )
            await message.answer("Что дальше?", reply_markup=video_kb())
        except Exception as e:
            await add_credits(uid, cost, "bonus", "Возврат: ошибка img2video")
            await message.answer(f"⚠️ Ошибка. Кредиты возвращены.\n{str(e)[:100]}", reply_markup=video_kb())
            logging.error(f"img2video error: {e}")
        finally:
            try:
                await thinking.delete()
            except Exception:
                pass

    asyncio.create_task(img2video_task())


# ── ИИ-аватар (липсинк, Kling Avatar) ──
AVATAR_MODELS = {
    "🟢 Kling Standard — 800 кр": {"model": "klingai/avatar-standard", "cost": 800,  "label": "Kling Standard"},
    "🔵 Kling Pro — 1800 кр":     {"model": "klingai/avatar-pro",      "cost": 1800, "label": "Kling Pro"},
}

def avatar_model_kb() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.row(KeyboardButton(text="🟢 Kling Standard — 800 кр"))
    b.row(KeyboardButton(text="🔵 Kling Pro — 1800 кр"))
    b.row(KeyboardButton(text="❌ Отмена"))
    return b.as_markup(resize_keyboard=True)

@router.message(F.text == "🗣 ИИ-аватар (липсинк)")
async def avatar_start(message: Message, state: FSMContext):
    bal = await get_balance(message.from_user.id)
    if bal < 800:
        await message.answer(f"❌ Нужно минимум *800 кр.* · У тебя *{bal} кр.*", parse_mode="Markdown", reply_markup=profile_kb())
        return
    await state.set_state(State_.avatar_photo)
    await message.answer(
        "🗣 *ИИ-аватар (синхронизация губ)*\n\n"
        "Выбери модель:\n"
        "🟢 *Kling Standard* — дешевле, быстрая, отличный липсинк\n"
        "🔵 *Kling Pro* — выше качество, мимика и движения\n\n"
        "_Аудио/текст — до 30 секунд._",
        parse_mode="Markdown", reply_markup=avatar_model_kb()
    )

@router.message(State_.avatar_photo, F.text.in_(AVATAR_MODELS.keys()))
async def avatar_choose_model(message: Message, state: FSMContext):
    m = AVATAR_MODELS[message.text]
    bal = await get_balance(message.from_user.id)
    if bal < m["cost"]:
        await state.clear()
        await message.answer(f"❌ Нужно *{m['cost']} кр.* · У тебя *{bal} кр.*", parse_mode="Markdown", reply_markup=profile_kb())
        return
    await state.update_data(avatar_model=m["model"], avatar_label=m["label"], cost=m["cost"])
    await message.answer(
        f"Модель: *{m['label']}* ✅  ·  💎 {m['cost']} кр.\n\n"
        "Отправь *фото лица* (чёткий портрет анфас) — оно «заговорит».",
        parse_mode="Markdown", reply_markup=cancel_kb()
    )

@router.message(State_.avatar_photo, F.photo)
async def avatar_photo_received(message: Message, state: FSMContext):
    data = await state.get_data()
    if not data.get("avatar_model"):
        await message.answer("Сначала выбери модель кнопкой выше 🙂", reply_markup=avatar_model_kb())
        return
    photo = message.photo[-1]
    file = await message.bot.get_file(photo.file_id)
    url = f"https://api.telegram.org/file/bot{message.bot.token}/{file.file_path}"
    await state.update_data(avatar_image=url)
    await state.set_state(State_.avatar_audio)
    await message.answer(
        "✅ Фото получено!\n\n"
        "Теперь — два варианта:\n"
        "🎤 Отправь *голосовое или аудио* (до 30 сек), ИЛИ\n"
        "✍️ *Напиши текст* — я озвучу его голосом ИИ.",
        parse_mode="Markdown", reply_markup=cancel_kb()
    )

async def _run_avatar(message: Message, state: FSMContext, audio_url: str):
    data = await state.get_data()
    image_url = data.get("avatar_image")
    cost = data.get("cost", 800)
    model_id = data.get("avatar_model", "klingai/avatar-standard")
    label = data.get("avatar_label", "Kling Avatar")
    if not image_url:
        await state.clear()
        await message.answer("Сначала отправь фото. Начни заново.", reply_markup=video_kb())
        return
    ok = await use_credits(message.from_user.id, "avatar", cost)
    if not ok:
        await state.clear()
        await message.answer("❌ Недостаточно кредитов.", reply_markup=profile_kb())
        return
    await state.clear()
    thinking = await message.answer(
        "🗣 Создаю говорящего аватара... (~2–4 мин)\n✅ Можешь пользоваться ботом — пришлю автоматически!",
        reply_markup=main_kb()
    )
    async def task():
        try:
            url = await generate_avatar(image_url, audio_url, model_id)
            async with httpx.AsyncClient(timeout=180) as client:
                vr = await client.get(url); vr.raise_for_status(); vid_bytes = vr.content
            b = await get_balance(message.from_user.id)
            await message.answer_video(
                BufferedInputFile(vid_bytes, filename="avatar.mp4"),
                caption=f"🗣 *ИИ-аватар готов!* ({label})\n\n💎 Потрачено: *{cost} кр.* · Остаток: *{b} кр.*",
                parse_mode="Markdown"
            )
            await message.answer("Что дальше?", reply_markup=video_kb())
        except Exception as e:
            await add_credits(message.from_user.id, cost, "bonus", "Возврат: ошибка аватара")
            await message.answer(f"⚠️ Ошибка генерации аватара. Кредиты возвращены.\n{str(e)[:120]}", reply_markup=video_kb())
            logging.error(f"Avatar error: {e}")
        finally:
            try: await thinking.delete()
            except Exception: pass
    asyncio.create_task(task())

@router.message(State_.avatar_audio, F.voice | F.audio)
async def avatar_audio_received(message: Message, state: FSMContext):
    obj = message.voice or message.audio
    file = await message.bot.get_file(obj.file_id)
    audio_url = f"https://api.telegram.org/file/bot{message.bot.token}/{file.file_path}"
    await _run_avatar(message, state, audio_url)

@router.message(State_.avatar_audio, F.text)
async def avatar_text_received(message: Message, state: FSMContext):
    if message.text and message.text.startswith("❌"):
        return  # отмену обработает общий хендлер
    thinking = await message.answer("🎙 Озвучиваю текст голосом ИИ...")
    try:
        audio_bytes = await generate_tts(message.text[:600])
    except Exception as e:
        try: await thinking.delete()
        except Exception: pass
        await message.answer(f"⚠️ Ошибка озвучки: {str(e)[:100]}", reply_markup=cancel_kb())
        return
    sent = await message.answer_audio(BufferedInputFile(audio_bytes, filename="voice.mp3"))
    obj = sent.audio or sent.voice
    file = await message.bot.get_file(obj.file_id)
    audio_url = f"https://api.telegram.org/file/bot{message.bot.token}/{file.file_path}"
    try: await thinking.delete()
    except Exception: pass
    await _run_avatar(message, state, audio_url)


# ── Соединение нескольких фото ──
combine_buffer: dict[int, dict] = {}  # uid -> {"photos": [...], "caption": str, "task": bool}

@router.message(F.text == "🔗 Соединить фото")
async def combine_start(message: Message, state: FSMContext):
    cost = 120
    bal = await get_balance(message.from_user.id)
    if bal < cost:
        await message.answer(f"❌ Нужно *{cost} кр.* · У тебя *{bal} кр.*", parse_mode="Markdown", reply_markup=profile_kb())
        return
    await state.set_state(State_.waiting_combine)
    await state.update_data(cost=cost)
    combine_buffer.pop(message.from_user.id, None)
    await message.answer(
        "🔗 *Соединить фото*  ·  💎 70 кредитов\n\n"
        "Отправь *2-4 фото одним альбомом* (выбери несколько сразу), "
        "и в подписи к ним напиши что сделать.\n\n"
        "Примеры подписи:\n"
        "• *посади этого человека на этот фон*\n"
        "• *объедини обоих людей на одном фото*\n"
        "• *надень одежду со второго фото на человека с первого*",
        parse_mode="Markdown", reply_markup=cancel_kb()
    )

@router.message(State_.waiting_combine, F.text == "❌ Отмена")
async def combine_cancel(message: Message, state: FSMContext):
    combine_buffer.pop(message.from_user.id, None)
    await state.clear()
    await message.answer("Отменено.", reply_markup=design_kb())

@router.message(State_.waiting_combine, F.photo)
async def combine_photo_received(message: Message, state: FSMContext):
    uid = message.from_user.id
    photo = message.photo[-1]
    file = await message.bot.get_file(photo.file_id)
    file_url = f"https://api.telegram.org/file/bot{message.bot.token}/{file.file_path}"

    if uid not in combine_buffer:
        combine_buffer[uid] = {"photos": [], "caption": "", "processing": False}
    combine_buffer[uid]["photos"].append(file_url)
    if message.caption:
        combine_buffer[uid]["caption"] = message.caption

    # Запустить отложенную обработку (ждём пока придут все фото альбома)
    if not combine_buffer[uid]["processing"]:
        combine_buffer[uid]["processing"] = True

        async def process_after_delay():
            await asyncio.sleep(2.5)  # ждём остальные фото альбома
            buf = combine_buffer.get(uid)
            if not buf:
                return
            photos = buf["photos"]
            caption = buf["caption"]
            combine_buffer.pop(uid, None)

            if len(photos) < 2:
                await message.answer(
                    "❌ Нужно минимум 2 фото. Отправь несколько фото одним альбомом.",
                    reply_markup=cancel_kb()
                )
                return

            if not caption:
                await message.answer(
                    "❌ Не вижу подписи. Отправь фото ещё раз и добавь в подписи что сделать "
                    "(например: *объедини этих людей*).",
                    parse_mode="Markdown", reply_markup=cancel_kb()
                )
                return

            data = await state.get_data()
            cost = data.get("cost", 120)
            ok = await use_credits(uid, "combine", cost)
            if not ok:
                await message.answer("❌ Недостаточно кредитов.", reply_markup=profile_kb())
                await state.clear()
                return
            await state.clear()

            thinking = await message.answer(
                f"🔗 Соединяю {len(photos)} фото... (~20-40 сек)",
                reply_markup=ReplyKeyboardRemove()
            )
            try:
                img_bytes, result_url = await generate_combine(photos, caption)
                bal = await get_balance(uid)
                try:
                    await thinking.delete()
                except Exception:
                    pass
                await message.answer_photo(
                    BufferedInputFile(img_bytes, filename="combined.png"),
                    caption="✅ Готово! NanoBanana PRO"
                )
                await message.answer(
                    f"📌 Запрос: _{caption}_\n\n"
                    f"💎 Потрачено: *{cost} кр.* · Остаток: *{bal} кр.*\n\n"
                    f"[📥 Скачать в высоком качестве]({result_url})",
                    parse_mode="Markdown", disable_web_page_preview=False
                )
                await message.answer("Что дальше?", reply_markup=design_kb())
                await log_request(uid, "combine", "nano-banana-pro-edit", cost)
            except Exception as e:
                await add_credits(uid, cost, "bonus", "Возврат: ошибка соединения")
                await message.answer(f"⚠️ Ошибка. Кредиты возвращены.\n{str(e)[:100]}", reply_markup=design_kb())
                logging.error(f"Combine error: {e}")

        asyncio.create_task(process_after_delay())

@router.message(State_.waiting_combine, F.text != "❌ Отмена")
async def combine_no_photo(message: Message):
    await message.answer("📸 Отправь 2-4 фото одним альбомом с подписью что сделать.")


@router.message(StateFilter(None), F.photo & F.caption, ~F.from_user.is_bot)
async def remix_photo_caption(message: Message, state: FSMContext):
    """Remix режим — фото + подпись сразу редактируется"""    
    cost = 120
    bal = await get_balance(message.from_user.id)
    if bal < cost:
        await message.answer(f"❌ Нужно *{cost} кр.* для редактирования фото · У тебя *{bal} кр.*", parse_mode="Markdown")
        return

    ok = await use_credits(message.from_user.id, "img2img_remix", cost)
    if not ok:
        await message.answer("❌ Недостаточно кредитов.", reply_markup=profile_kb())
        return

    photo = message.photo[-1]
    file = await message.bot.get_file(photo.file_id)
    image_url = f"https://api.telegram.org/file/bot{message.bot.token}/{file.file_path}"
    prompt = message.caption

    thinking = await message.answer("✏️ *Редактирую фото...*\n\n⏱ ~15-30 сек", parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())

    try:
        img_bytes, result_url = await generate_img2img(image_url, prompt)
        bal = await get_balance(message.from_user.id)
        try:
            await thinking.delete()
        except Exception:
            pass
        await message.answer_photo(
            BufferedInputFile(img_bytes, filename="edited.png"),
            caption=f"✅ Готово! Качество 2K · NanoBanana PRO"
        )
        await message.answer(
            f"📌 Запрос: _{prompt}_\n\n"
            f"💎 Потрачено: *{cost} кр.* · Остаток: *{bal} кр.*\n\n"
            f"[📥 Скачать в высоком качестве]({result_url})",
            parse_mode="Markdown",
            disable_web_page_preview=False
        )
        await message.answer("📸 Отправь ещё фото с подписью для редактирования!", reply_markup=design_kb())
        await log_request(message.from_user.id, "img2img_remix", "nano-banana-pro", cost)
    except Exception as e:
        await add_credits(message.from_user.id, cost, "bonus", "Возврат: ошибка remix")
        await message.answer(f"⚠️ Ошибка. Кредиты возвращены.\n{str(e)[:100]}", reply_markup=design_kb())
        logging.error(f"Remix error: {e}")


# ══════════════════════════════════════════════════════
#  РЕФЕРАЛЫ
# ══════════════════════════════════════════════════════

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
async def cb_choose_credits_method(callback: CallbackQuery):
    pid = callback.data.replace("buy_credits_", "")
    pack = CREDIT_PACKS.get(pid)
    if not pack: return
    await callback.message.answer(
        f"💎 *{pack['name']}*\n\nВыбери способ оплаты:",
        parse_mode="Markdown",
        reply_markup=pay_method_kb("credits", pid)
    )
    await callback.answer()

@router.callback_query(F.data == "show_annual")
async def cb_show_annual(callback: CallbackQuery):
    text = (
        "📅 *Годовые подписки* — выгоднее на 2 месяца!\n"
        "_Платишь сразу за год, кредиты зачисляются полностью._\n\n"
        "⭐️ *Basic год — 3 900₽* (вместо 4 680₽)\n• 24 000 кредитов\n\n"
        "👑 *Pro год — 10 900₽* (вместо 13 080₽)  🔥\n• 54 000 кредитов + скидка 25% на фото\n\n"
        "💎 *Premium год — 22 900₽* (вместо 27 480₽)  ⭐️\n• 108 000 кредитов + безлимит чат + скидка 50% на фото\n\n"
        "💡 _Экономия ~2 300–4 600₽ в год._"
    )
    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=plans_annual_inline_kb())
    except Exception:
        await callback.message.answer(text, parse_mode="Markdown", reply_markup=plans_annual_inline_kb())
    await callback.answer()

@router.callback_query(F.data == "show_monthly")
async def cb_show_monthly(callback: CallbackQuery):
    text = (
        "👑 *Подписки Vatan AI* (помесячно)\n\n"
        "⭐️ *Basic — 390₽/мес* · 2 000 кр\n"
        "👑 *Pro — 1 090₽/мес* · 4 500 кр + скидка 25% 🔥\n"
        "💎 *Premium — 2 290₽/мес* · 9 000 кр + безлимит чат + скидка 50% ⭐️\n\n"
        "_Или выбери годовую — 2 месяца в подарок._"
    )
    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=plans_inline_kb())
    except Exception:
        await callback.message.answer(text, parse_mode="Markdown", reply_markup=plans_inline_kb())
    await callback.answer()

@router.callback_query(F.data.startswith("buyyear_"))
async def cb_choose_year_method(callback: CallbackQuery):
    pid = callback.data.replace("buyyear_", "")
    plan = PLANS_ANNUAL.get(pid)
    if not plan: return
    await callback.message.answer(
        f"{plan['emoji']} *{plan['name']}* — {plan['credits']} кредитов на год\n\nВыбери способ оплаты:",
        parse_mode="Markdown",
        reply_markup=pay_method_kb("planyear", pid)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("buy_plan_"))
async def cb_choose_plan_method(callback: CallbackQuery):
    pid = callback.data.replace("buy_plan_", "")
    plan = PLANS.get(pid)
    if not plan: return
    await callback.message.answer(
        f"{plan['emoji']} *{plan['name']}* — {plan['description']}\n\nВыбери способ оплаты:",
        parse_mode="Markdown",
        reply_markup=pay_method_kb("plan", pid)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("paystars_"))
async def cb_pay_stars(callback: CallbackQuery):
    _, kind, item_id = callback.data.split("_", 2)
    if kind == "credits":
        pack = CREDIT_PACKS.get(item_id)
        if not pack: return
        await callback.bot.send_invoice(
            chat_id=callback.from_user.id,
            title=f"Vatan AI — {pack['name']}",
            description=f"Пополнение: {pack['credits']} кредитов",
            payload=f"credits_{item_id}",
            currency="XTR",
            prices=[LabeledPrice(label=pack["name"], amount=pack["stars"])],
        )
    elif kind == "planyear":
        plan = PLANS_ANNUAL.get(item_id)
        if not plan: return
        await callback.bot.send_invoice(
            chat_id=callback.from_user.id,
            title=f"Vatan AI {plan['name']}",
            description=f"{plan['credits']} кредитов на год",
            payload=f"planyear_{item_id}",
            currency="XTR",
            prices=[LabeledPrice(label=plan["name"], amount=plan["stars"])],
        )
    elif kind == "course":
        await callback.bot.send_invoice(
            chat_id=callback.from_user.id,
            title=COURSE["name"],
            description="Доступ к курсу + 1000 кредитов",
            payload="course_main",
            currency="XTR",
            prices=[LabeledPrice(label=COURSE["name"], amount=COURSE["stars"])],
        )
    else:
        plan = PLANS.get(item_id)
        if not plan: return
        await callback.bot.send_invoice(
            chat_id=callback.from_user.id,
            title=f"Vatan AI {plan['name']} — 30 дней",
            description=plan["description"],
            payload=f"plan_{item_id}",
            currency="XTR",
            prices=[LabeledPrice(label=f"Vatan AI {plan['name']}", amount=plan["stars"])],
        )
    await callback.answer()

@router.callback_query(F.data.startswith("payrub_"))
async def cb_pay_rub(callback: CallbackQuery):
    if not YOOKASSA_TOKEN:
        await callback.message.answer(
            "💳 Оплата картой скоро будет доступна. Пока используй ⭐️ Telegram Stars.",
        )
        await callback.answer()
        return
    _, kind, item_id = callback.data.split("_", 2)
    if kind == "credits":
        pack = CREDIT_PACKS.get(item_id)
        if not pack: return
        await callback.bot.send_invoice(
            chat_id=callback.from_user.id,
            title=f"Vatan AI — {pack['name']}",
            description=f"Пополнение: {pack['credits']} кредитов",
            payload=f"credits_{item_id}",
            provider_token=YOOKASSA_TOKEN,
            currency="RUB",
            prices=[LabeledPrice(label=pack["name"], amount=pack["rub"] * 100)],
            need_email=True, send_email_to_provider=True,
        )
    elif kind == "planyear":
        plan = PLANS_ANNUAL.get(item_id)
        if not plan: return
        await callback.bot.send_invoice(
            chat_id=callback.from_user.id,
            title=f"Vatan AI {plan['name']}",
            description=f"{plan['credits']} кредитов на год",
            payload=f"planyear_{item_id}",
            provider_token=YOOKASSA_TOKEN,
            currency="RUB",
            prices=[LabeledPrice(label=plan["name"], amount=plan["rub"] * 100)],
            need_email=True, send_email_to_provider=True,
        )
    elif kind == "course":
        await callback.bot.send_invoice(
            chat_id=callback.from_user.id,
            title=COURSE["name"],
            description="Доступ к курсу + 1000 кредитов",
            payload="course_main",
            provider_token=YOOKASSA_TOKEN,
            currency="RUB",
            prices=[LabeledPrice(label=COURSE["name"], amount=COURSE["rub"] * 100)],
            need_email=True, send_email_to_provider=True,
        )
    else:
        plan = PLANS.get(item_id)
        if not plan: return
        await callback.bot.send_invoice(
            chat_id=callback.from_user.id,
            title=f"Vatan AI {plan['name']} — 30 дней",
            description=plan["description"],
            payload=f"plan_{item_id}",
            provider_token=YOOKASSA_TOKEN,
            currency="RUB",
            prices=[LabeledPrice(label=f"Vatan AI {plan['name']}", amount=plan["rub"] * 100)],
            need_email=True, send_email_to_provider=True,
        )
    await callback.answer()

@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery): await query.answer(ok=True)

@router.message(F.successful_payment)
async def on_payment(message: Message):
    payload = message.successful_payment.invoice_payload
    stars   = message.successful_payment.total_amount
    currency = message.successful_payment.currency
    uid     = message.from_user.id

    item_name = "Доступ к сервису Vatan AI"
    if payload.startswith("credits_"):
        pack = CREDIT_PACKS.get(payload.replace("credits_", ""))
        if pack:
            item_name = f"Vatan AI — {pack['name']}"
            new_bal = await add_credits(uid, pack["credits"], "purchase", f"Покупка: {pack['name']}")
            await message.answer(f"✅ *Оплата прошла!*\n\n💎 +{pack['credits']} кредитов\n💰 Баланс: *{new_bal} кр.*", parse_mode="Markdown", reply_markup=main_kb())
    elif payload.startswith("planyear_"):
        plan = PLANS_ANNUAL.get(payload.replace("planyear_", ""))
        if plan:
            item_name = f"Vatan AI {plan['name']}"
            await set_plan(uid, plan["base"], plan["credits"], plan["days"])
            bal = await get_balance(uid)
            await message.answer(f"✅ *{plan['name']} активирован на год!*\n\n💎 +{plan['credits']} кредитов\n💰 Баланс: *{bal} кр.*", parse_mode="Markdown", reply_markup=main_kb())
    elif payload.startswith("plan_"):
        plan = PLANS.get(payload.replace("plan_", ""))
        if plan:
            item_name = f"Vatan AI {plan['name']}"
            await set_plan(uid, payload.replace("plan_", ""), plan["credits"], plan["days"])
            bal = await get_balance(uid)
            await message.answer(f"✅ *{plan['name']} активирован!*\n\n💎 +{plan['credits']} кредитов\n💰 Баланс: *{bal} кр.*", parse_mode="Markdown", reply_markup=main_kb())
    elif payload.startswith("course"):
        item_name = COURSE["name"]
        await add_credits(uid, COURSE["credits"], "purchase", "Бонус за курс")
        link = await setting_get("course_link", "")
        if link:
            await message.answer(
                f"✅ *Доступ к курсу открыт!*\n\n🎓 Заходи в закрытый канал с уроками:\n{link}\n\n🎁 Также начислено {COURSE['credits']} кредитов для практики. Удачи в обучении!",
                parse_mode="Markdown", reply_markup=main_kb()
            )
        else:
            await message.answer(
                f"✅ *Оплата курса прошла!*\n\n🎁 Начислено {COURSE['credits']} кредитов. Доступ к урокам пришлю в ближайшее время.",
                parse_mode="Markdown", reply_markup=main_kb()
            )
            try:
                await message.bot.send_message(ADMIN_ID, f"🎓 Новая покупка КУРСА! @{message.from_user.username or uid} ({uid}). Выдай доступ — ссылка не задана (/set_course_link).")
            except Exception:
                pass

    # Автоматическая регистрация чека в «Мой налог» — только для рублёвых платежей
    if currency == "RUB":
        try:
            if await nalog_is_connected():
                amount_rub = stars / 100  # сумма в копейках -> рубли
                receipt_url = await nalog_add_income(item_name, amount_rub)
                if receipt_url:
                    await message.answer(
                        f"🧾 Чек сформирован и отправлен в налоговую.\n[Открыть чек]({receipt_url})",
                        parse_mode="Markdown", disable_web_page_preview=True
                    )
        except Exception as e:
            logging.error(f"Nalog income error: {e}")
            # Уведомить админа, чтобы не потерять чек
            try:
                await message.bot.send_message(ADMIN_ID, f"⚠️ Не удалось зарегистрировать чек в «Мой налог» (платёж {stars/100}₽). Зарегистрируй вручную. Ошибка: {str(e)[:150]}")
            except Exception:
                pass

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

@router.message(Command("nalog_login"))
async def cmd_nalog_login(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    connected = await nalog_is_connected()
    status = "✅ уже подключён" if connected else "❌ не подключён"
    await state.set_state(State_.nalog_phone)
    await message.answer(
        f"🧾 *Вход в «Мой налог»* ({status})\n\n"
        "Введи номер телефона, привязанный к «Мой налог», в формате *79991234567* "
        "(11 цифр, без + и пробелов):",
        parse_mode="Markdown"
    )

@router.message(Command("nalog_status"))
async def cmd_nalog_status(message: Message):
    if message.from_user.id != ADMIN_ID: return
    if await nalog_is_connected():
        inn = await setting_get("nalog_inn", "—")
        phone = await setting_get("nalog_phone", "—")
        await message.answer(f"🧾 «Мой налог»: ✅ подключён\nИНН: {inn}\nТелефон: {phone}\n\nЧеки регистрируются автоматически после каждой оплаты картой.")
    else:
        await message.answer("🧾 «Мой налог»: ❌ не подключён.\nВыполни /nalog_login")

@router.message(Command("nalog_logout"))
async def cmd_nalog_logout(message: Message):
    if message.from_user.id != ADMIN_ID: return
    for k in ("nalog_refresh_token", "nalog_access_token", "nalog_token_expires"):
        await setting_set(k, "")
    await message.answer("🧾 «Мой налог» отключён. Авторегистрация чеков остановлена.")

@router.message(State_.nalog_phone)
async def nalog_phone_entered(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await state.clear(); return
    phone = "".join(ch for ch in (message.text or "") if ch.isdigit())
    if len(phone) != 11:
        await message.answer("❌ Нужно 11 цифр, например 79991234567. Попробуй ещё раз:")
        return
    try:
        challenge = await nalog_request_sms(phone)
    except Exception as e:
        await state.clear()
        await message.answer(f"❌ Не удалось запросить SMS. Проверь номер и попробуй снова (/nalog_login).\n{str(e)[:150]}")
        return
    await state.update_data(nalog_phone=phone, nalog_challenge=challenge)
    await state.set_state(State_.nalog_code)
    await message.answer("📲 Отправил запрос. Введи *код из SMS*:", parse_mode="Markdown")

@router.message(State_.nalog_code)
async def nalog_code_entered(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await state.clear(); return
    code = "".join(ch for ch in (message.text or "") if ch.isdigit())
    data = await state.get_data()
    phone = data.get("nalog_phone"); challenge = data.get("nalog_challenge")
    if not code:
        await message.answer("❌ Введи код из SMS (только цифры):")
        return
    try:
        inn = await nalog_verify_sms(phone, code, challenge)
        await nalog_access_token()  # сразу получим рабочий токен
    except Exception as e:
        await state.clear()
        await message.answer(f"❌ Не подтвердилось. Начни заново: /nalog_login\n{str(e)[:150]}")
        return
    await state.clear()
    await message.answer(
        f"✅ *«Мой налог» подключён!*\nИНН: {inn}\n\n"
        "Теперь после каждой оплаты картой бот будет сам регистрировать доход и отправлять чек покупателю. "
        "Налог посчитается в приложении «Мой налог».\n\n"
        "Проверить статус: /nalog_status\nОтключить: /nalog_logout",
        parse_mode="Markdown"
    )

@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id != ADMIN_ID: return
    total, paid, today, stars = await admin_stats()
    await message.answer(
        f"🔐 *Админ Vatan AI v3*\n\n👥 Всего: *{total}*\n👑 Платных: *{paid}*\n📨 Сегодня: *{today}*\n⭐️ Stars: *{stars}*",
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

@router.message(Command("users"))
async def cmd_users(message: Message):
    if message.from_user.id != ADMIN_ID: return
    rows = await db_all(
        "SELECT id, full_name, username, credits, plan, credits_total, registered_at "
        "FROM users ORDER BY registered_at DESC LIMIT 20"
    )
    if not rows:
        await message.answer("Пользователей нет")
        return
    lines = ["👥 *Последние 20 пользователей*\n"]
    for r in rows:
        plan_label = {"free": "Free", "pro": "👑Pro", "team": "💎Team"}.get(r["plan"], "Free")
        name = r["full_name"] or r["username"] or "Аноним"
        lines.append(
            f"👤 *{name}*\n"
            f"🆔 `{r['id']}`\n"
            f"💎 {r['credits']} кр. · {plan_label}\n"
        )
    await message.answer("\n".join(lines), parse_mode="Markdown")

@router.message(Command("user"))
async def cmd_user(message: Message):
    if message.from_user.id != ADMIN_ID: return
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("Формат: /user USER_ID")
        return
    user = await get_user(int(parts[1]))
    if not user:
        await message.answer("❌ Пользователь не найден")
        return
    plan_label = {"free": "Free", "pro": "👑 Pro", "team": "💎 Team"}.get(user["plan"], "Free")
    expires = f"\n📅 До: *{user['plan_expires'][:10]}*" if user["plan_expires"] else ""
    rows = await db_all(
        "SELECT amount, description, created_at FROM transactions "
        "WHERE user_id=? ORDER BY created_at DESC LIMIT 5",
        (user["id"],)
    )
    tx_lines = []
    for r in rows:
        sign = "+" if r["amount"] > 0 else ""
        tx_lines.append(f"`{r['created_at'][:10]}` {sign}{r['amount']} — {r['description']}")
    text = (
        f"👤 *Профиль пользователя*\n\n"
        f"Имя: *{user['full_name'] or 'Нет'}*\n"
        f"Username: @{user['username'] or 'нет'}\n"
        f"🆔 `{user['id']}`\n"
        f"Plan: *{plan_label}*{expires}\n"
        f"💎 Кредиты: *{user['credits']}*\n"
        f"🏅 Всего: *{user['credits_total']}*\n"
        f"👥 Рефералов: *{user['referrals_count']}*\n\n"
        f"*Последние транзакции:*\n" + "\n".join(tx_lines or ["Нет"])
    )
    await message.answer(text, parse_mode="Markdown")

@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message):
    if message.from_user.id != ADMIN_ID: return
    parts = message.text.split(None, 1)
    if len(parts) < 2:
        await message.answer(
            "Формат: /broadcast текст сообщения\n\n"
            "Пример: /broadcast 🚀 Бот обновлён! Нажми /start чтобы получить новое меню."
        )
        return
    text = parts[1]
    users = await db_all("SELECT id FROM users")
    total = len(users)
    sent = 0
    failed = 0
    status_msg = await message.answer(f"📤 Отправляю {total} пользователям...")
    for user in users:
        try:
            await message.bot.send_message(user["id"], text, parse_mode="Markdown", reply_markup=main_kb())
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)  # Не превышать лимиты Telegram
    try:
        await status_msg.edit_text(
            f"✅ *Рассылка завершена*\n\n"
            f"📤 Отправлено: *{sent}*\n"
            f"❌ Ошибок: *{failed}*",
            parse_mode="Markdown"
        )
    except Exception:
        pass


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

    logging.info(f"🚀 Vatan AI Bot v3.1 ФОРМАТЫ запущен | @{BOT_USERNAME}")
    logging.info("✅ ВЕРСИЯ С ВЫБОРОМ ФОРМАТА 9:16 16:9 — если видишь это, новый код работает")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    asyncio.run(main())
