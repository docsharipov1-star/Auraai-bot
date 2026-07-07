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
VPS_API_URL   = os.getenv("VPS_API_URL", "http://92.53.124.13:9090")
VPS_API_SECRET = os.getenv("VPS_API_SECRET", "alina_vps_2024")
YOOKASSA_TOKEN = os.getenv("YOOKASSA_TOKEN", "")  # provider token из BotFather (ЮKassa)
DB_PATH       = "/app/data/auraai.db"
FREE_CREDITS  = 150
REFERRAL_BONUS = 50

anthropic_client = None
openai_client    = None
deepseek_client  = None
kie_client       = None

PLANS = {
    "basic":   {"name": "Basic",   "emoji": "⭐️", "stars": 325,  "rub": 390,  "credits": 2000, "days": 30, "unlimited": False, "description": "2 000 токенов на 30 дней"},
    "pro":     {"name": "Pro",     "emoji": "👑", "stars": 900,  "rub": 1090, "credits": 4500, "days": 30, "unlimited": False, "discount": 25, "description": "4 500 токенов + скидка 25% на фото и картинки"},
    "premium": {"name": "Premium", "emoji": "💎", "stars": 1900, "rub": 2290, "credits": 9000, "days": 30, "unlimited": True, "discount": 50, "description": "9 000 токенов + БЕЗЛИМИТ на AI-чат + скидка 50% на фото и картинки"},
}

# Годовые подписки — 2 месяца в подарок (платишь ~за 10, токены сразу за год)
PLANS_ANNUAL = {
    "basic":   {"name": "Basic год",   "emoji": "⭐️", "stars": 3250,  "rub": 3900,  "credits": 24000,  "days": 365, "base": "basic"},
    "pro":     {"name": "Pro год",     "emoji": "👑", "stars": 9000,  "rub": 10900, "credits": 54000,  "days": 365, "base": "pro"},
    "premium": {"name": "Premium год", "emoji": "💎", "stars": 19000, "rub": 22900, "credits": 108000, "days": 365, "base": "premium"},
}

# Курс по нейросетям
COURSE = {"name": "Курс «Заработок на ИИ-картинках»", "rub": 2900, "stars": 2400, "credits": 1000}

SALES_PROMPT = (
    "Ты — дружелюбный и уверенный менеджер по продажам онлайн-курса AuraAI. "
    "Твоя задача — помочь человеку и мягко довести его до покупки курса.\n\n"
    "О КУРСЕ:\n"
    "• Название: курс «Заработок на ИИ-картинках».\n"
    "• Цена: 2 900₽. Можно оплатить картой (рубли) или Telegram Stars прямо в боте.\n"
    "• Для кого: для новичков с нуля — студентов, предпринимателей, всех кто хочет новую профессию или подработку из дома. Опыт и диплом не нужны, нужен только телефон.\n"
    "• Что внутри: как обрабатывать фото, делать рекламу и карточки товаров, оживлять снимки в видео, и как брать на этом платные заказы.\n"
    "• Результат: после курса человек умеет делать ИИ-визуал и может брать заказы или делать визуал для своего бизнеса без дизайнера.\n"
    "• Бонус: при покупке курса начисляется 1 000 токенов на бота AuraAI, чтобы сразу практиковаться.\n\n"
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

CREDIT_PACKS = {
    "pack_500":   {"name": "500 кредитов",    "stars": 80,   "rub": 99,   "credits": 500},
    "pack_2000":  {"name": "2 000 токенов",  "stars": 290,  "rub": 349,  "credits": 2000},
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

    "coach": (
        "Ты — Аура, мудрый коуч-наставник. Тебе дан нумерологический профиль человека (числа жизненного пути, судьбы, "
        "души, личности и личного года), а также личные данные. Используй их как живую карту, а не гороскоп.\n\n"
        "ТВОЯ ЗАДАЧА:\n"
        "— Помочь найти призвание, карьерный путь и сферу, где человек расцветёт.\n"
        "— Выявить сильные стороны и зоны роста на основе числового профиля.\n"
        "— Задавать глубокие вопросы, которые помогают человеку прийти к ответу самому.\n"
        "— Предлагать конкретные шаги и практики для самопознания.\n\n"
        "СТИЛЬ:\n"
        "— Тёплый, вдохновляющий, без мистики и пустых обещаний.\n"
        "— Нумерология — инструмент для рефлексии, а не судьба. Говори об этом честно.\n"
        "— Пиши как коуч: отражай, спрашивай, вдохновляй. Не читай лекции.\n"
        "— 3–5 предложений за раз, один вопрос в конце.\n\n"
        "ТЕМЫ: призвание, карьера, образование, сильные стороны, предназначение, личностный рост, выбор пути."
    ),

    "relations": (
        "Ты — Аура, глубокий советник по отношениям. Ты работаешь как терапевт пар с богатым опытом.\n\n"

        "ЗАПРЕЩЕНО:\n"
        "— Советы в лоб: «уйди от него», «поговори», «прости», «дай время», «займись собой»\n"
        "— Штампы и банальности\n"
        "— Осуждать кого-либо из участников ситуации\n"
        "— Делать выводы не зная контекста\n"
        "— Несколько вопросов подряд\n\n"

        "КАК ТЫ РАБОТАЕШЬ:\n"
        "Ты слышишь не только слова но и то, что за ними. "
        "«Он меня бесит» — за этим может быть боль непонимания, страх потери, усталость от борьбы. "
        "Твоя задача — помочь человеку увидеть свою ситуацию ГЛУБЖЕ чем он видит сам.\n\n"

        "ЛИНЗЫ ЧЕРЕЗ КОТОРЫЕ ТЫ СМОТРИШЬ:\n"
        "— Стили привязанности: тревожный цепляется, избегающий дистанцируется — и они притягиваются\n"
        "— 4 всадника Готтмана: критика, презрение, защита, стена молчания — какой здесь?\n"
        "— Языки любви Чепмена: возможно они просто говорят на разных языках\n"
        "— NVC: за каждым обвинением — невысказанная потребность\n"
        "— Созависимость и границы: где заканчивается забота и начинается растворение в другом\n"
        "— Паттерны из детства: откуда этот страх, эта реакция, этот сценарий\n\n"

        "АЛГОРИТМ:\n"
        "1. Отрази точно что слышишь — эмоцию, боль, потребность\n"
        "2. Задай ОДИН вопрос который вскрывает суть — или сделай наблюдение которое удивит\n"
        "3. Когда контекст ясен — помоги увидеть паттерн или предложи конкретный инструмент\n\n"

        "СТИЛЬ: живой, без осуждения, иногда прямой. 4–6 предложений. "
        "Говори как умный близкий человек который понимает отношения глубоко."
    ),

    "health_psy": (
        "Ты — Аура, наставник по психологическому здоровью и телесному благополучию.\n\n"

        "ЗАПРЕЩЕНО:\n"
        "— Банальные советы: «больше отдыхай», «меньше стресса», «занимайся спортом»\n"
        "— Несколько вопросов подряд\n"
        "— Медицинские диагнозы и назначения\n"
        "— Пугать или катастрофизировать\n\n"

        "КАК ТЫ РАБОТАЕШЬ:\n"
        "Ты понимаешь что тело и психика — единое целое. "
        "Хроническая усталость — это не лень, это сигнал. Боль в спине может быть непрожитым напряжением. "
        "Ты помогаешь человеку услышать что говорит его тело и что за этим стоит.\n\n"

        "ТВОИ ИНСТРУМЕНТЫ:\n"
        "— Психосоматика: какие эмоции живут в каком теле (горло — невысказанное, "
        "живот — тревога и контроль, плечи — ответственность и груз)\n"
        "— Гештальт по Погодину: контакт с телом здесь и сейчас, живое переживание. "
        "Рекомендуй youtube.com/@pogodinigor\n"
        "— Дыхание: 4-7-8 для тревоги, физиологический вздох для стресса (двойной вдох носом + выдох)\n"
        "— Сканирование тела: пройтись вниманием с головы до ног, заметить где напряжение\n"
        "— Релаксация Джекобсона: поочерёдно напрягать и расслаблять группы мышц\n"
        "— Заземление 5-4-3-2-1: назвать 5 вещей которые видишь, 4 которые слышишь...\n"
        "— Сон и восстановление: конкретные практики, а не «ложись пораньше»\n"
        "— Движение как терапия: прогулка меняет биохимию мозга за 20 минут\n\n"

        "АЛГОРИТМ:\n"
        "1. Услышь что именно болит или беспокоит — телесно и эмоционально\n"
        "2. Свяжи симптом с возможной эмоциональной причиной — не как диагноз, а как гипотезу\n"
        "3. Предложи одну практику прямо сейчас — конкретно, по шагам\n\n"

        "СТИЛЬ: заботливый, точный, без запугивания. 4–6 предложений. "
        "При серьёзных симптомах мягко рекомендуй врача — один раз."
    ),

    "psy": (
        "Ты — Аура, глубокий AI-психолог. Ты работаешь как опытный терапевт с 20 годами практики.\n\n"

        "ЗАПРЕЩЕНО АБСОЛЮТНО:\n"
        "— Давать поверхностные советы: «напиши прости», «поговори с ней», «отдохни», «займись собой»\n"
        "— Штампы: «я понимаю тебя», «это нормально», «всё будет хорошо», «ты молодец»\n"
        "— Задавать несколько вопросов подряд\n"
        "— Читать лекции о психологии\n"
        "— Делать выводы быстро — сначала пойми, что реально происходит\n\n"

        "КАК РАБОТАЕТ НАСТОЯЩИЙ ТЕРАПЕВТ:\n"
        "Когда человек говорит «я послал её» — терапевт не говорит «напиши прости». "
        "Он слышит: боль, злость, возможно сожаление или облегчение — и отражает это ТОЧНО. "
        "«Ты послал её... и сейчас внутри что — облегчение? злость? пустота?» "
        "Терапевт копает ГЛУБЖЕ: что стояло за этим? что накопилось? что осталось несказанным?\n\n"

        "ТВОЙ АЛГОРИТМ:\n"
        "1. Услышь что за словами — эмоция, боль, потребность, страх\n"
        "2. Отрази это ТОЧНО и неожиданно метко — не банально\n"
        "3. Если ситуация неясна — задай ОДИН точный вопрос который вскрывает суть\n"
        "4. Если ситуация ясна — сделай наблюдение как терапевт: «похоже, за этой злостью стоит что-то большее»\n"
        "5. Технику предлагай только когда человек готов — не с первого сообщения\n\n"

        "ГЛУБИНА КОТОРОЙ ТЫ РАБОТАЕШЬ:\n"
        "— Паттерны из детства и привязанность (почему человек реагирует именно так)\n"
        "— Защитные механизмы (злость часто прикрывает боль, агрессия — страх потери)\n"
        "— Незавершённые ситуации (что осталось невысказанным, что зависло)\n"
        "— Телесные ощущения (где в теле это живёт прямо сейчас)\n"
        "— Ценности и смыслы (что это говорит о том, что для него важно)\n\n"

        "СТИЛЬ:\n"
        "— Живой, тёплый, иногда немного прямой — как друг который умеет слушать глубоко\n"
        "— 3–6 предложений обычно. Развёрнуто только когда ведёшь через практику\n"
        "— Ссылайся на то, что человек говорил раньше\n"
        "— Иногда одна точная фраза лучше трёх советов\n\n"

        "БЕЗОПАСНОСТЬ:\n"
        "— Без диагнозов и лекарств\n"
        "— Кризис: поддержи + 8-800-2000-122 (бесплатно, РФ)"
    ),
}

# Слова-маркеры возможного кризиса — для психолог-агента (грубый фильтр, не диагноз)
CRISIS_WORDS = [
    "суицид", "покончить", "не хочу жить", "не хочется жить", "убить себя",
    "убью себя", "свести счёты", "свести счеты", "смысла жить", "нет смысла жить",
    "самоубийств", "порезать себя", "режу себя", "причинить себе", "наложить на себя руки",
    "хочу умереть", "лучше умереть", "уйти из жизни",
]

# Текст поддержки при кризисном сигнале
CRISIS_REPLY = (
    "Мне очень жаль, что тебе сейчас так тяжело. То, что ты чувствуешь, важно, "
    "и ты не обязан справляться с этим в одиночку. 💛\n\n"
    "Я — бот и не могу заменить живого человека рядом. Если есть возможность, "
    "поговори с тем, кому доверяешь, или с тем, кто умеет поддержать:\n\n"
    "• Телефон доверия — *8-800-2000-122* (круглосуточно, бесплатно, анонимно)\n\n"
    "Ты важен, и рядом есть те, кто может помочь."
)

def is_crisis(text: str) -> bool:
    t = (text or "").lower()
    return any(w in t for w in CRISIS_WORDS)

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
                registered_at       TEXT    DEFAULT CURRENT_TIMESTAMP,
                real_name           TEXT,
                birth_date          TEXT,
                numerology_profile  TEXT
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
                tool TEXT NOT NULL DEFAULT 'chat',
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_chat_history_user ON chat_history(user_id);
            CREATE INDEX IF NOT EXISTS idx_chat_history_tool ON chat_history(user_id, tool);
            CREATE TABLE IF NOT EXISTS mood_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                score INTEGER NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_mood_user ON mood_log(user_id);
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
            "INSERT INTO transactions (user_id,amount,type,description,balance) VALUES (?,?,'bonus','Приветственные токены',?)",
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

async def call_text_ai(prompt: str, system: str, model_id: str, uid: int = 0, use_history: bool = False, image_url: str = None, history_msgs: list = None, timeout_s: int = 45, web: bool = False, tool: str = "chat") -> str:
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
        history = await get_history(uid, tool)
        messages = history + [{"role": "user", "content": user_content}]
    else:
        messages = [{"role": "user", "content": user_content}]

    try:
        if provider == "anthropic" and anthropic_client:
            base_kwargs = dict(
                model="claude-sonnet-4-6", max_tokens=2048,
                system=system, messages=messages,
            )
            resp = None
            if web:
                # Пытаемся с веб-поиском; при любой ошибке — откатываемся на обычный ответ
                try:
                    resp = await asyncio.wait_for(
                        anthropic_client.messages.create(
                            **base_kwargs,
                            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}],
                        ),
                        timeout=max(timeout_s, 45)
                    )
                except Exception as e:
                    logging.warning(f"Web search failed, fallback to plain Claude: {e}")
                    resp = None
            if resp is None:
                resp = await asyncio.wait_for(
                    anthropic_client.messages.create(**base_kwargs),
                    timeout=timeout_s
                )
            # При веб-поиске в ответе несколько блоков — берём только текстовые
            result = "".join(
                getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text"
            ).strip()
            if not result:
                result = "Не удалось сформировать ответ. Попробуй переформулировать 🙂"
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
            await add_to_history(uid, "user", prompt, tool)
            await add_to_history(uid, "assistant", result, tool)

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
        "resolution": "2K"
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

def _preserve_face_video(prompt: str) -> str:
    return (prompt.strip() +
            ". Keep the EXACT same person and face throughout the whole video: same facial features, "
            "same face shape, same identity. Do NOT distort, fatten, slim or change the face. "
            "Animate naturally while keeping the person clearly recognizable as themselves.")


def _preserve_face(prompt: str) -> str:
    return (
        "Edit this photo. Requested change: " + prompt.strip() + ". "
        "IDENTITY LOCK — ABSOLUTELY CRITICAL: keep the EXACT SAME person. "
        "Preserve the face 100% identical to the original photo: same facial features, same face shape and jawline, "
        "same eyes, nose, mouth, eyebrows, cheekbones, hairline, skin tone and skin texture. "
        "Do NOT change the person's weight, face width or body size. Do NOT make the face or body fatter, rounder, puffier, thinner or wider. "
        "Do NOT beautify, do NOT smooth the skin, do NOT slim or fatten, do NOT change age, do NOT change proportions. "
        "The result MUST be instantly recognizable as the very same person, like the same photo lightly edited. "
        "Change ONLY what is explicitly requested above and keep the person's identity and likeness completely unchanged."
    )


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
                "prompt": _preserve_face(prompt),
                "image_urls": [data_uri],
                "aspect_ratio": aspect,
                "resolution": "2K"
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
                "prompt": _preserve_face(prompt),
                "image_urls": data_uris,
                "aspect_ratio": aspect,
                "resolution": "2K"
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
                "prompt": _preserve_face_video(prompt),
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

def main_kb(is_admin: bool = False) -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.row(KeyboardButton(text="💡 GPTs/Claude/Gemini"))
    b.row(KeyboardButton(text="🧠 Психолог"))
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
    b.row(KeyboardButton(text="🤖 Команда агентов"))
    b.row(
        KeyboardButton(text="❓ Помощь"),
        KeyboardButton(text="📕 База знаний"),
    )
    if is_admin:
        b.row(KeyboardButton(text="📊 Доктора"), KeyboardButton(text="💰 Финансы бизнеса"))
        b.row(KeyboardButton(text="🗓 Таблицы клиники"))
    return b.as_markup(resize_keyboard=True)

def text_tools_kb() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.row(KeyboardButton(text="💬 AI Чат"))
    b.row(KeyboardButton(text="🧠 Психолог"))
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
    b.row(KeyboardButton(text="🅰 Claude Sonnet — 10 тк."))
    b.row(KeyboardButton(text="🐋 DeepSeek V3 — 5 тк."))
    b.row(KeyboardButton(text="✳️ GPT-4o — 15 тк."))
    b.row(KeyboardButton(text="🏠 В главное меню"))
    return b.as_markup(resize_keyboard=True)

def cancel_kb() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.row(KeyboardButton(text="❌ Отмена"))
    b.row(KeyboardButton(text="🏠 В главное меню"))
    return b.as_markup(resize_keyboard=True)

def profile_kb() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.row(
        KeyboardButton(text="💎 Купить токены"),
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
    waiting_video_photo_text = State()
    waiting_video_aspect = State()
    nalog_phone = State()  # админ: ввод телефона для входа в «Мой налог»
    nalog_code  = State()  # админ: ввод SMS-кода
    course_chat = State()  # чат с ИИ-менеджером курса
    avatar_photo = State()  # ИИ-аватар: ожидание фото
    avatar_audio = State()  # ИИ-аватар: ожидание аудио или текста
    agent_menu  = State()  # команда агентов: выбор режима
    agent_auto  = State()  # команда агентов: авто-оркестр
    agent_solo  = State()  # команда агентов: прямой диалог
    finance_menu  = State()  # финансовый агент: меню
    finance_input = State()  # финансовый агент: ввод отчёта
    biz_menu  = State()  # финансы бизнеса: меню
    biz_input = State()  # финансы бизнеса: ввод отчёта
    biz_date  = State()  # финансы бизнеса: отчёт за конкретную дату
    calllist      = State()   # список для обзвона Алиной
    numerology    = State()   # ввод имени и даты рождения для нумерологии

user_tool:  dict[int, str] = {}
user_model: dict[int, str] = {}
user_image_model: dict[int, str] = {}
async def get_history(uid: int, tool: str = "chat") -> list:
    rows = await db_all(
        "SELECT role, content FROM chat_history WHERE user_id=? AND tool=? ORDER BY created_at ASC",
        (uid, tool)
    )
    return [{"role": r["role"], "content": r["content"]} for r in rows]

async def add_to_history(uid: int, role: str, content: str, tool: str = "chat"):
    await db_run(
        "INSERT INTO chat_history (user_id, tool, role, content) VALUES (?, ?, ?, ?)",
        (uid, tool, role, content)
    )
    # Держать только последние 20 сообщений на каждый агент
    await db_run(
        "DELETE FROM chat_history WHERE user_id=? AND tool=? AND id NOT IN ("
        "SELECT id FROM chat_history WHERE user_id=? AND tool=? ORDER BY created_at DESC LIMIT 20)",
        (uid, tool, uid, tool)
    )

async def clear_history(uid: int, tool: str = None):
    if tool:
        await db_run("DELETE FROM chat_history WHERE user_id=? AND tool=?", (uid, tool))
    else:
        await db_run("DELETE FROM chat_history WHERE user_id=?", (uid,))

# ── Настроение (для агента «Аура») ────────────────────
MOOD_LABELS = {1: "😟 Очень плохо", 2: "😕 Так себе", 3: "😐 Нормально", 4: "🙂 Хорошо", 5: "😄 Отлично"}

async def save_user_profile(uid: int, real_name: str, birth_date: str, numerology_profile: str):
    await db_run(
        "UPDATE users SET real_name=?, birth_date=?, numerology_profile=? WHERE id=?",
        (real_name, birth_date, numerology_profile, uid)
    )

async def get_user_profile(uid: int) -> dict:
    row = await db_get("SELECT real_name, birth_date, numerology_profile FROM users WHERE id=?", (uid,))
    if row:
        return {"real_name": row["real_name"], "birth_date": row["birth_date"], "numerology_profile": row["numerology_profile"]}
    return {}

async def build_context_prefix(uid: int) -> str:
    """Добавляет в начало системного промпта что мы знаем о пользователе."""
    p = await get_user_profile(uid)
    parts = []
    if p.get("real_name"):
        parts.append(f"Имя пользователя: {p['real_name']}")
    if p.get("birth_date"):
        parts.append(f"Дата рождения: {p['birth_date']}")
    if p.get("numerology_profile"):
        parts.append(f"Нумерологический профиль:\n{p['numerology_profile']}")
    if parts:
        return "О ПОЛЬЗОВАТЕЛЕ (используй если уместно):\n" + "\n".join(parts) + "\n\n"
    return ""

async def log_mood(uid: int, score: int):
    await db_run("INSERT INTO mood_log (user_id, score) VALUES (?, ?)", (uid, score))

async def get_mood_summary(uid: int) -> str:
    rows = await db_all(
        "SELECT score, created_at FROM mood_log WHERE user_id=? ORDER BY created_at DESC LIMIT 7", (uid,)
    )
    if not rows:
        return "Пока нет записей о настроении. Загляни сюда после нескольких чек-инов 🙂"
    lines = ["📊 *Твоё настроение за последние отметки:*\n"]
    for r in rows:
        label = MOOD_LABELS.get(r["score"], "—")
        lines.append(f"`{r['created_at'][:10]}` — {label}")
    avg = sum(r["score"] for r in rows) / len(rows)
    lines.append(f"\nСредняя оценка: *{avg:.1f}* из 5")
    return "\n".join(lines)

TOOL_MAP = {
    "💬 AI Чат":     ("chat",      10),
    "🧠 Психолог":      ("psy",        15),
    "🔮 Предназначение": ("coach",      20),
    "💕 Отношения":     ("relations",  15),
    "🌿 Здоровье":      ("health_psy", 10),
}

MODEL_MAP = {
    "🅰 Claude Sonnet — 10 тк.": "claude",
    "🐋 DeepSeek V3 — 5 тк.":   "deepseek",
    "✳️ GPT-4o — 15 тк.":       "gpt4o",
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
    "psy":        "Расскажи, что тебя беспокоит. Я помогу разобраться и подскажу конкретные шаги. Это не замена врачу 💛",
    "coach":      "Напиши своё полное имя и дату рождения (ДД.ММ.ГГГГ) — составлю твой числовой профиль и поговорим о призвании.",
    "relations":  "Расскажи о своей ситуации в отношениях. Я здесь — без осуждения 💕",
    "health_psy": "Что сейчас с твоим состоянием и самочувствием? Расскажи — поищем, откуда это идёт 🌿",
}

# ── Агент «Аура»: инструменты, клавиатуры, чек-ин настроения ──
PSY_TOOLS = {
    "🫁 Подышать": (
        "Проведи меня прямо сейчас через короткое дыхательное упражнение для успокоения, "
        "по шагам, в спокойном тёплом тоне."
    ),
    "🔁 Разобрать мысль": (
        "Помоги мне разобрать тревожную или негативную мысль по методу КПТ: "
        "задай вопросы, чтобы я её записал, нашёл искажения и переформулировал."
    ),
    "🌍 Заземлиться": (
        "Проведи меня через технику заземления 5-4-3-2-1, чтобы вернуться в момент здесь и сейчас."
    ),
    "📓 Дневник": (
        "Предложи мне 2–3 мягких вопроса для дневника, чтобы я выгрузил мысли и чувства за сегодня."
    ),
}

def psy_kb() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.row(KeyboardButton(text="🧠 Психолог"), KeyboardButton(text="🔮 Предназначение"))
    b.row(KeyboardButton(text="💕 Отношения"), KeyboardButton(text="🌿 Здоровье"))
    b.row(KeyboardButton(text="🔁 Разобрать мысль"), KeyboardButton(text="📓 Дневник"))
    b.row(KeyboardButton(text="🗑 Очистить историю чата"))
    b.row(KeyboardButton(text="🏠 В главное меню"))
    return b.as_markup(resize_keyboard=True)

def mood_checkin_kb():
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="😟", callback_data="mood:1"),
        InlineKeyboardButton(text="😕", callback_data="mood:2"),
        InlineKeyboardButton(text="😐", callback_data="mood:3"),
        InlineKeyboardButton(text="🙂", callback_data="mood:4"),
        InlineKeyboardButton(text="😄", callback_data="mood:5"),
    )
    return b.as_markup()

_PSY_INTRO_PROMPTS = {
    "psy": (
        "Ты — Аура, AI-психолог. Напиши короткое (2–3 предложения) уникальное тёплое приветствие "
        "для нового сеанса. Каждый раз — разное: иногда про усталость, иногда про тревогу, "
        "иногда просто про то что жизнь бывает тяжёлой. Заканчивай мягким приглашением рассказать — "
        "НЕ вопросом, а ощущением безопасности. Только сам текст, без кавычек."
    ),
    "relations": (
        "Ты — Аура, советник по отношениям. Напиши короткое (2–3 предложения) уникальное тёплое "
        "приветствие. Каждый раз — разное: про близость, про боль разлуки, про непонимание, про одиночество рядом. "
        "Без вопросов — только присутствие и приглашение говорить. Только текст."
    ),
    "health_psy": (
        "Ты — Аура, наставник по психологическому здоровью. Напиши короткое (2–3 предложения) "
        "уникальное тёплое приветствие. Каждый раз — разное: про усталость тела, про стресс, "
        "про то как тело хранит всё что мы переживаем. Без вопросов — только мягкое присутствие. Только текст."
    ),
}

async def _gen_intro(tool_id: str) -> str:
    """Генерирует уникальное приветствие через Claude."""
    if anthropic_client is None:
        import random
        defaults = {
            "psy": [
                "Привет, я Аура 💛 Я здесь — просто рядом. Расскажи, что на душе.",
                "Иногда просто нужно место, где можно выдохнуть. Ты здесь — это уже важно 💛",
                "Сегодня было непросто? Или что-то накопилось? Я слушаю.",
                "Я Аура. Здесь можно говорить как есть — без фильтров и осуждения 🌿",
            ],
            "relations": [
                "Привет, я Аура 💕 Отношения — это живое и иногда очень больное. Я слушаю.",
                "Близость с другим человеком — это и самое тёплое, и самое сложное. Расскажи, что происходит 💕",
                "Иногда слова застревают внутри, когда говорить не с кем. Я здесь — расскажи.",
                "Я Аура. Без осуждения и готовых советов — только пространство для тебя 💕",
            ],
            "health_psy": [
                "Привет, я Аура 🌿 Тело помнит всё. Расскажи, что сейчас происходит.",
                "Когда внутри неспокойно — тело это знает первым. Что сейчас чувствуешь? 🌿",
                "Я Аура. Здесь можно говорить о теле, об усталости, о том, что уже давно копится.",
                "Тело и душа — одно. Расскажи, что тебя тревожит — начнём разбираться вместе 🌿",
            ],
        }
        options = defaults.get(tool_id, ["Привет, я Аура. Расскажи, что тебя привело сюда."])
        return random.choice(options)
    try:
        resp = await anthropic_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=120,
            messages=[{"role": "user", "content": _PSY_INTRO_PROMPTS[tool_id]}],
        )
        return resp.content[0].text.strip()
    except Exception:
        return "Привет, я Аура 💛 Я здесь. Расскажи, что сейчас происходит."

async def send_psy_intro(message: Message):
    text = await _gen_intro("psy")
    await message.answer(text, reply_markup=mood_checkin_kb())
    await message.answer("Пиши как есть — я слушаю 🌿", reply_markup=psy_kb())

async def send_relations_intro(message: Message):
    text = await _gen_intro("relations")
    await message.answer(text, reply_markup=psy_kb())

async def send_health_intro(message: Message):
    text = await _gen_intro("health_psy")
    await message.answer(text, reply_markup=psy_kb())

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
        text = f"✨ *Добро пожаловать в AuraAI!*\n\n🎁 Тебе начислено *{bal} токенов* для старта\n\nВыбери раздел:"
    else:
        bal = await get_balance(message.from_user.id)
        text = f"👋 С возвращением, *{message.from_user.first_name}*!\n\n💎 Токены: *{bal}*\n\nВыбери раздел:"

    await message.answer(text, parse_mode="Markdown", reply_markup=main_kb(message.from_user.id == ADMIN_ID))

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
        "🎁 Бонус: 1 000 токенов на бота для практики\n\n"
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
        "У тебя уже есть бесплатные токены на старте. Попробуй — а потом возвращайся за полным курсом 😉",
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
    await message.answer(f"🏠 *Главное меню*\n\n💎 Токены: *{bal}*", parse_mode="Markdown", reply_markup=main_kb(message.from_user.id == ADMIN_ID))

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
    await message.answer(f"🏠 *Главное меню*\n\n💎 Токены: *{bal}*", parse_mode="Markdown", reply_markup=main_kb(message.from_user.id == ADMIN_ID))

@router.message(F.text == "📊 Доктора")
async def btn_doctors(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await doctors_cmd(message)

@router.message(F.text == "💰 Финансы бизнеса")
async def btn_biz(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await biz_start(message, state)

@router.message(F.text == "🗓 Таблицы клиники")
async def btn_tables(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer(
        "🗓 *Таблицы клиники*\n\nДоступ к каждой таблице открой: «по ссылке: Читатель».\n\n"
        "📅 Смены день/ночь → отчёт по врачам:\n`/setshift ссылка`\n\n"
        "💼 Зарплата персонала → расход в /biz:\n`/setsalary ссылка`\n\n"
        "📋 Простая таблица (Дата|Пациенты|Выручка|Расходы) → /biz:\n`/setsheet ссылка`\n\n"
        "Списки/удаление: /visits · /sheets · /delshift N · /delsheet N\n"
        "Отчёты — кнопки «📊 Доктора» и «💰 Финансы бизнеса».",
        parse_mode="Markdown")

@router.message(F.text == "❌ Отмена")
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено.", reply_markup=main_kb())

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
        "🎙 *Аудио с ИИ*\n\n🎵 Google Lyria 2 — генерация музыки по описанию\n💎 50 токенов за трек\n\n🔊 ElevenLabs TTS — озвучка текста голосом\n💎 20 токенов",
        parse_mode="Markdown", reply_markup=audio_kb()
    )

@router.message(F.text == "🎬 Видео будущего")
async def section_video(message: Message):
    await message.answer(
        "🎬 *Видео будущего*\n\n🎬 Seedance 2.0 — видео нового поколения до 5 сек\n💎 150 токенов\n\n🎥 Kling 1.6 — проверенная классика до 5 сек\n💎 150 токенов\n\n🖼➡️🎬 Фото в видео — оживи своё фото\n💎 100 токенов",
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
        f"💎 Токены: *{bal}*\n"
        f"🏅 Всего начислено: *{user['credits_total'] if user else 0}*",
        parse_mode="Markdown", reply_markup=profile_kb()
    )

@router.message(F.text == "💎 Купить токены")
async def buy_credits(message: Message):
    await message.answer(
        "💎 *Купить токены*\n\nОплата картой (рубли) или Telegram Stars.\nКредиты зачисляются мгновенно и не сгорают.\n\nВыбери пакет:",
        parse_mode="Markdown", reply_markup=credits_pack_kb()
    )

@router.message(F.text == "👑 Подписки")
async def buy_plans(message: Message):
    user = await get_user(message.from_user.id)
    plan = user["plan"] if user else "free"

    text = (
        "👑 *Подписки AuraAI*\n"
        "_Чем выше тариф — тем дешевле каждая генерация._\n\n"

        f"{'✅ ' if plan=='basic' else ''}⭐️ *Basic — 390₽/мес*\n"
        "• 2 000 токенов\n"
        "• Хватит на ~16 фото или 5 видео\n"
        "• Все функции бота\n\n"

        f"{'✅ ' if plan=='pro' else ''}👑 *Pro — 1 090₽/мес*  🔥 выгодно\n"
        "• 4 500 токенов\n"
        "• 🏷 Скидка *25%* на фото и картинки\n"
        "• Хватит на ~50 фото или 11 видео\n"
        "• Все функции бота\n\n"

        f"{'✅ ' if plan=='premium' else ''}💎 *Premium — 2 290₽/мес*  ⭐️ максимум\n"
        "• 9 000 токенов\n"
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
    lines = [f"📋 *История*\n\nБаланс: *{bal} тк.*\n"]
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
        await message.answer(f"❌ Нужно минимум *{base_cost} тк.* · У тебя *{bal} тк.*\n\nПополни баланс:", parse_mode="Markdown", reply_markup=profile_kb())
        return

    user_tool[message.from_user.id] = tool_id

    # Психолог, Отношения, Здоровье — всегда Claude
    if tool_id in ("psy", "relations", "health_psy"):
        total_cost = base_cost + TEXT_MODELS["claude"]["cost"]
        bal2 = await get_balance(message.from_user.id)
        if bal2 < total_cost:
            await message.answer(f"❌ Нужно *{total_cost} тк.* · У тебя *{bal2} тк.*", parse_mode="Markdown", reply_markup=profile_kb())
            return
        user_model[message.from_user.id] = "claude"
        await state.update_data(tool=tool_id, model="claude", cost=total_cost)
        await state.set_state(State_.waiting_text)
        if tool_id == "psy":
            await send_psy_intro(message)
        elif tool_id == "relations":
            await send_relations_intro(message)
        else:
            await send_health_intro(message)
        return

    # Коуч-предназначение — сначала собираем имя + дату
    if tool_id == "coach":
        total_cost = base_cost + TEXT_MODELS["claude"]["cost"]
        bal2 = await get_balance(message.from_user.id)
        if bal2 < total_cost:
            await message.answer(f"❌ Нужно *{total_cost} тк.* · У тебя *{bal2} тк.*", parse_mode="Markdown", reply_markup=profile_kb())
            return
        user_model[message.from_user.id] = "claude"
        await state.update_data(tool="coach", model="claude", cost=total_cost)
        await state.set_state(State_.numerology)
        b = ReplyKeyboardBuilder()
        b.row(KeyboardButton(text="🏠 В главное меню"))
        await message.answer(
            "🔮 *Коуч по предназначению*\n\n"
            "Напиши своё полное имя и дату рождения в одном сообщении.\n\n"
            "Пример:\n`Иванова Мария Сергеевна 15.03.1992`",
            parse_mode="Markdown",
            reply_markup=b.as_markup(resize_keyboard=True)
        )
        return

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
        await message.answer(f"❌ Нужно *{total_cost} тк.* · У тебя *{bal} тк.*", parse_mode="Markdown", reply_markup=profile_kb())
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
            f"{model_info['emoji']} *{model_info['name']}*  ·  💎 {total_cost} токенов\n\n"
            f"Фото сохранено! Теперь отправь его снова вместе с вопросом:",
            parse_mode="Markdown", reply_markup=cancel_kb()
        )
    else:
        if tool_id == "psy":
            await send_psy_intro(message)
        else:
            await message.answer(
                f"{model_info['emoji']} *{model_info['name']}*  ·  💎 {total_cost} токенов\n\n{hint}",
                parse_mode="Markdown", reply_markup=cancel_kb()
            )

@router.message(State_.choose_model, F.text == "🏠 В главное меню")
async def model_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🏠 Главное меню", reply_markup=main_kb())

@router.callback_query(F.data.startswith("mood:"))
async def mood_checkin(callback: CallbackQuery):
    try:
        score = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer(); return
    await log_mood(callback.from_user.id, score)
    label = MOOD_LABELS.get(score, "")
    try:
        await callback.message.edit_text(f"Спасибо, что поделился. Отметил: {label}")
    except Exception:
        pass
    await callback.answer("Записал 💛")

async def _transcribe_voice(bot, voice_obj) -> str:
    """Скачиваем голосовое и транскрибируем через OpenAI Whisper."""
    if not openai_client:
        raise Exception("OpenAI ключ не настроен")
    file = await bot.get_file(voice_obj.file_id)
    url = f"https://api.telegram.org/file/bot{bot.token}/{file.file_path}"
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(url)
        r.raise_for_status()
        audio_bytes = r.content
    import io
    audio_io = io.BytesIO(audio_bytes)
    audio_io.name = "voice.ogg"
    resp = await openai_client.audio.transcriptions.create(
        model="whisper-1",
        file=audio_io,
        language="ru",
    )
    return resp.text.strip()


@router.message(State_.waiting_text, F.voice)
async def process_voice_message(message: Message, state: FSMContext):
    """Голосовые сообщения в диалоге с психолог-агентами."""
    data = await state.get_data()
    tool_id = data.get("tool", "chat")
    PSY_TOOLS_IDS = ("psy", "relations", "health_psy", "coach")

    note = await message.answer("🎙 Слушаю...", reply_markup=ReplyKeyboardRemove())
    try:
        text = await _transcribe_voice(message.bot, message.voice)
    except Exception as e:
        await note.edit_text(f"Не смог распознать голос: {str(e)[:80]}")
        return
    await note.delete()

    # Показываем что распознали
    await message.answer(f"🎙 «{text}»")

    # Дальше — как обычный текст
    model_id = data.get("model", "claude")
    cost = data.get("cost", 10)
    is_psy = tool_id in PSY_TOOLS_IDS

    ok = await use_credits(message.from_user.id, tool_id, cost)
    if not ok:
        await message.answer("❌ Недостаточно токенов.", reply_markup=profile_kb())
        await state.clear(); return

    thinking = await message.answer("💭")
    try:
        system = SYSTEM_PROMPTS.get(tool_id, SYSTEM_PROMPTS["chat"])
        use_history = tool_id in ("chat",) + PSY_TOOLS_IDS
        result = await call_text_ai(text, system, "claude", uid=message.from_user.id, use_history=use_history, tool=tool_id)
        await log_request(message.from_user.id, tool_id, model_id, cost)

        try:
            await thinking.edit_text(result)
        except Exception:
            await message.answer(result)

        # Остаёмся в диалоге
        await state.set_state(State_.waiting_text)
        await state.update_data(tool=tool_id, model=model_id, cost=cost)
        import random
        continuations = ["Я здесь 💛", "Слушаю тебя.", "Продолжай — я рядом.", "Говори — я слушаю.", "Рядом с тобой 💕"]
        if is_psy:
            await message.answer(random.choice(continuations), reply_markup=psy_kb())
        else:
            await message.answer("💬 Продолжай:", reply_markup=cancel_kb())

    except Exception as e:
        logging.error(f"Voice process error: {e}")
        try:
            await thinking.edit_text("Что-то пошло не так. Попробуй ещё раз.")
        except Exception:
            await message.answer("Что-то пошло не так.")
        await state.clear()


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

    # Кнопки-инструменты работают во всех psy-агентах
    PSY_TOOLS_ALL = ("psy", "relations", "health_psy", "coach")
    if tool_id in PSY_TOOLS_ALL:
        if user_text == "📊 Моё настроение":
            await message.answer(
                await get_mood_summary(message.from_user.id),
                reply_markup=psy_kb()
            )
            await state.set_state(State_.waiting_text)
            await state.update_data(tool=tool_id, model=model_id, cost=cost)
            return
        if user_text in PSY_TOOLS:
            user_text = PSY_TOOLS[user_text]

    # Психолог-агент: проверка кризисного сигнала ДО списания кредитов и обращения к ИИ
    if tool_id == "psy" and is_crisis(user_text):
        await message.answer(CRISIS_REPLY, parse_mode="Markdown")
        await state.set_state(State_.waiting_text)
        await state.update_data(tool=tool_id, model=model_id, cost=cost)
        await message.answer("Я рядом. Можешь продолжать писать.", reply_markup=psy_kb())
        return

    ok = await use_credits(message.from_user.id, tool_id, cost)
    if not ok:
        await message.answer("❌ Недостаточно токенов.", reply_markup=profile_kb())
        await state.clear(); return

    await state.clear()
    PSY_TOOLS_IDS = ("psy", "relations", "health_psy", "coach")
    is_psy = tool_id in PSY_TOOLS_IDS
    thinking = await message.answer("💭", reply_markup=ReplyKeyboardRemove())

    try:
        system = SYSTEM_PROMPTS.get(tool_id, SYSTEM_PROMPTS["chat"])
        # Для psy-агентов добавляем что знаем о пользователе (имя, дата, нумерология)
        if is_psy:
            ctx = await build_context_prefix(message.from_user.id)
            if ctx:
                system = ctx + system
        use_history = tool_id in ("chat", "psy", "relations", "health_psy", "coach")
        gen_model = "claude" if is_psy else model_id
        result = await call_text_ai(user_text, system, gen_model, uid=message.from_user.id, use_history=use_history, image_url=image_url, tool=tool_id)
        bal    = await get_balance(message.from_user.id)
        model_info = TEXT_MODELS.get(model_id, TEXT_MODELS["claude"])

        await log_request(message.from_user.id, tool_id, model_id, cost)

        chunks = [result[i:i+3500] for i in range(0, len(result), 3500)]
        for i, chunk in enumerate(chunks):
            if i == 0:
                if is_psy:
                    # Для психолог-агентов — без parse_mode, чтобы Markdown от Claude не ломал Telegram
                    try:
                        await thinking.edit_text(chunk)
                    except Exception:
                        await message.answer(chunk)
                else:
                    try:
                        await thinking.edit_text(
                            f"{model_info['emoji']} {model_info['name']}\n\n{chunk}\n\n"
                            f"Потрачено: {cost} тк. · Остаток: {bal} тк.",
                        )
                    except Exception:
                        await message.answer(
                            f"{model_info['emoji']} {model_info['name']}\n\n{chunk}\n\n"
                            f"Потрачено: {cost} тк. · Остаток: {bal} тк.",
                        )
            else:
                await message.answer(chunk)

        if tool_id in ("chat",) + PSY_TOOLS_IDS:
            await state.set_state(State_.waiting_text)
            await state.update_data(tool=tool_id, model=model_id, cost=cost)
            if is_psy:
                import random
                continuations = [
                    "Я здесь 💛", "Слушаю тебя.", "Продолжай — я рядом.",
                    "Я никуда не ухожу 🌿", "Говори — я слушаю.",
                    "Ты в безопасности здесь.", "Рядом с тобой 💕",
                ]
                await message.answer(random.choice(continuations), reply_markup=psy_kb())
            else:
                await message.answer("💬 Продолжай:", reply_markup=cancel_kb())
        else:
            await message.answer("Готово! Выбери следующий инструмент:", reply_markup=text_tools_kb())

    except asyncio.TimeoutError:
        await add_credits(message.from_user.id, cost, "bonus", "Возврат: таймаут")
        try:
            await thinking.edit_text("⏱ Время вышло (15 сек). Токены возвращены. Попробуй ещё раз.")
        except Exception:
            await message.answer("⏱ Время вышло (15 сек). Токены возвращены. Попробуй ещё раз.")
        if tool_id == "chat":
            await state.set_state(State_.waiting_text)
            await state.update_data(tool=tool_id, model=model_id, cost=cost)
            await message.answer("Попробуй ещё раз:", reply_markup=cancel_kb())
        else:
            await message.answer("Выбери инструмент:", reply_markup=text_tools_kb())
        logging.error(f"Text AI timeout [{tool_id}/{model_id}]")

    except Exception as e:
        err_text = str(e)
        logging.error(f"Text AI error [{tool_id}/{model_id}]: {err_text}")
        await add_credits(message.from_user.id, cost, "bonus", "Возврат: ошибка AI")
        try:
            await thinking.edit_text(f"⚠️ {err_text[:200]}")
        except Exception:
            pass
        await message.answer(f"Что-то пошло не так. Попробуй ещё раз.\n\nДеталь: {err_text[:200]}")
        PSY_TOOLS_IDS = ("psy", "relations", "health_psy", "coach")
        if tool_id in ("chat",) + PSY_TOOLS_IDS:
            await state.set_state(State_.waiting_text)
            await state.update_data(tool=tool_id, model=model_id, cost=cost)
            await message.answer("Напиши ещё раз:", reply_markup=psy_kb() if tool_id in PSY_TOOLS_IDS else cancel_kb())
        else:
            await message.answer("Выбери инструмент:", reply_markup=text_tools_kb())

# ══════════════════════════════════════════════════════
#  ГЕНЕРАЦИЯ КАРТИНОК
# ══════════════════════════════════════════════════════

def image_mode_kb() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.row(KeyboardButton(text="✏️ С нуля по описанию"))
    b.row(KeyboardButton(text="🖼 На основе моего фото"))
    b.row(KeyboardButton(text="❌ Отмена"), KeyboardButton(text="🏠 В главное меню"))
    return b.as_markup(resize_keyboard=True)

def aspect_kb() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.row(KeyboardButton(text="⬛ 1:1 Квадрат"))
    b.row(KeyboardButton(text="📱 9:16 Вертикальное"), KeyboardButton(text="🖥 16:9 Горизонтальное"))
    b.row(KeyboardButton(text="🖼 4:3"), KeyboardButton(text="📷 3:4"))
    b.row(KeyboardButton(text="❌ Отмена"), KeyboardButton(text="🏠 В главное меню"))
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
        await message.answer(f"❌ Нужно *{cost} тк.* · У тебя *{bal} тк.*", parse_mode="Markdown", reply_markup=profile_kb())
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
        f"*{message.text}*  ·  💎 {cost} токенов\n\n"
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

async def _generate_edit(message: Message, state: FSMContext):
    data = await state.get_data()
    base_photo = data.get("base_photo"); prompt = (data.get("base_caption") or "").strip()
    aspect = data.get("aspect", "1:1"); cost = data.get("cost", 50)
    model = data.get("image_model", "nano")
    if not (base_photo and prompt):
        await message.answer("Нужны фото и описание.", reply_markup=cancel_kb()); return
    ok = await use_credits(message.from_user.id, f"image_{model}", cost)
    if not ok:
        await message.answer("❌ Недостаточно токенов.", reply_markup=profile_kb()); await state.clear(); return
    await state.clear()
    thinking = await message.answer("🎨 Редактирую фото... (~15-30 сек)\nМожно вернуться в меню.", reply_markup=main_kb())
    try:
        bal = await get_balance(message.from_user.id)
        img_bytes, _ = await generate_img2img(base_photo, prompt, aspect)
        try:
            await thinking.delete()
        except Exception:
            pass
        await message.answer_photo(BufferedInputFile(img_bytes, filename="image.png"),
            caption=f"🎨 Готово · Формат {aspect}\n\n💎 Потрачено: {cost} тк. · Остаток: {bal} тк.")
        await state.set_state(State_.waiting_image)
        await state.update_data(image_model=model, cost=cost, aspect=aspect, base_photo=base_photo, base_caption=None)
        await message.answer("✅ Готово! Пришли ещё описание для этого фото — отредактирую снова. Или меню 👇",
                             reply_markup=design_kb())
    except Exception as e:
        await add_credits(message.from_user.id, cost, "bonus", "Возврат: ошибка")
        await message.answer(f"⚠️ Ошибка. Токены возвращены.\n{str(e)[:150]}", reply_markup=design_kb())

@router.message(State_.waiting_image, F.text.in_(ASPECT_MAP.keys()))
async def image_aspect_selected(message: Message, state: FSMContext):
    aspect = ASPECT_MAP[message.text]
    await state.update_data(aspect=aspect)
    data = await state.get_data()
    model = data.get("image_model", "dalle")
    if model in ("video", "kling"):
        await message.answer(
            f"Формат: *{aspect}* ✅\n\nКак создать видео?",
            parse_mode="Markdown", reply_markup=video_mode_kb()
        )
    elif data.get("base_photo") and data.get("base_caption"):
        await _generate_edit(message, state)
    elif data.get("base_photo"):
        await message.answer(
            f"Формат: *{aspect}* ✅\n\nТеперь опиши, что изменить на фото:\n\n"
            "Примеры: *сделай фон космическим* · *стиль аниме* · *добавь снег*",
            parse_mode="Markdown", reply_markup=cancel_kb()
        )
    else:
        await message.answer(
            f"Формат: *{aspect}* ✅\n\nТеперь опиши картинку которую хочешь создать:\n\n"
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
    await state.update_data(waiting_base_photo=True, base_caption=None, base_photo=None)
    await message.answer(
        "📸 Отправь своё фото-основу.\n"
        "Можно сразу добавить описание подписью к фото — тогда отвечу быстрее.",
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
            if message.caption:
                await state.update_data(base_caption=message.caption.strip())
            await message.answer(
                "✅ Фото получено!\n\nТеперь выбери формат (размер) результата:",
                reply_markup=aspect_kb()
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
        await message.answer("❌ Недостаточно токенов.", reply_markup=profile_kb())
        await state.clear(); return

    await state.clear()
    # Для фоновых задач (музыка/видео) оставляем меню чтобы можно было запускать другое
    if model in ("music", "kling", "video"):
        initial_text = "⏳ Запускаю генерацию..."
        thinking = await message.answer(initial_text, reply_markup=main_kb())
    else:
        thinking = await message.answer("🎨 Генерирую картинку... (~15-30 сек)\nМожно вернуться в меню — генерация продолжится.", reply_markup=main_kb())

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
                        caption=f"🎵 *Музыка готова!*\n\n💎 Потрачено: *{cost} тк.* · Остаток: *{b} тк.*",
                        parse_mode="Markdown"
                    )
                    await message.answer("Что дальше?", reply_markup=audio_kb())
                except Exception as e:
                    await add_credits(message.from_user.id, cost, "bonus", "Возврат: ошибка музыки")
                    await message.answer(f"⚠️ Ошибка генерации музыки. Токены возвращены.\n{str(e)[:100]}", reply_markup=audio_kb())
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
                        url = await generate_img2video(_kling_base, _kling_prompt, _kling_aspect)
                    else:
                        url = await generate_video_kling(_kling_prompt, _kling_aspect)
                    async with httpx.AsyncClient(timeout=180) as client:
                        vr = await client.get(url)
                        vr.raise_for_status()
                        video_bytes = vr.content
                    b = await get_balance(message.from_user.id)
                    await message.answer_video(
                        BufferedInputFile(video_bytes, filename="video.mp4"),
                        caption=f"🎥 *Kling 1.6*\n\n💎 Потрачено: *{cost} тк.* · Остаток: *{b} тк.*",
                        parse_mode="Markdown"
                    )
                    await message.answer("Что дальше?", reply_markup=video_kb())
                except Exception as e:
                    await add_credits(message.from_user.id, cost, "bonus", "Возврат: ошибка видео")
                    await message.answer(f"⚠️ Ошибка генерации видео. Токены возвращены.\n{str(e)[:100]}", reply_markup=video_kb())
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
                caption=f"🔊 *ElevenLabs TTS*\n\n💎 Потрачено: *{cost} тк.* · Остаток: *{bal} тк.*",
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
                        caption=f"🎬 *Seedance 2.0*\n\n💎 Потрачено: *{cost} тк.* · Остаток: *{b} тк.*",
                        parse_mode="Markdown"
                    )
                    await message.answer("Что дальше?", reply_markup=video_kb())
                except Exception as e:
                    await add_credits(message.from_user.id, cost, "bonus", "Возврат: ошибка видео")
                    await message.answer(f"⚠️ Ошибка генерации видео. Токены возвращены.\n{str(e)[:100]}", reply_markup=video_kb())
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
                img_bytes, _ = await generate_img2img(base_photo, prompt, aspect)
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
                caption=f"🎨 *{model_name}*  ·  Формат {aspect}\n\n💎 Потрачено: *{cost} тк.* · Остаток: *{bal} тк.*",
                parse_mode="Markdown"
            )
            # вернуть в режим генерации, чтобы следующий текст снова сработал
            await state.set_state(State_.waiting_image)
            await state.update_data(image_model=model, cost=cost, aspect=aspect, base_photo=base_photo)
            await message.answer(
                "✅ Готово! Напиши следующий запрос — сделаю ещё.\n"
                "Или выбери другое в меню ниже 👇",
                reply_markup=design_kb()
            )

        await log_request(message.from_user.id, f"media_{model}", model, cost)

    except asyncio.TimeoutError:
        await add_credits(message.from_user.id, cost, "bonus", "Возврат: таймаут")
        await message.answer("⏱ Время вышло. Токены возвращены.")
        kb = audio_kb() if model == "music" else (video_kb() if model == "video" else design_kb())
        await message.answer("Попробуй снова:", reply_markup=kb)

    except Exception as e:
        await add_credits(message.from_user.id, cost, "bonus", "Возврат: ошибка")
        await message.answer(f"⚠️ Ошибка. Токены возвращены.\n{str(e)[:150]}")
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
        await message.answer(f"❌ Нужно *{cost} тк.* · У тебя *{bal} тк.*", parse_mode="Markdown", reply_markup=profile_kb())
        return
    await state.set_state(State_.waiting_image)
    await state.update_data(image_model="music", cost=cost)
    await message.answer(
        f"🎵 *Google Lyria 2*  ·  💎 {cost} токенов\n\n"
        f"Опиши музыку которую хочешь создать:\n\n"
        f"Пример: *энергичный рок трек для мотивации, гитара и барабаны*",
        parse_mode="Markdown", reply_markup=cancel_kb()
    )

@router.message(F.text == "🎬 Создать видео Seedance")
async def video_generate(message: Message, state: FSMContext):
    cost = 400
    bal  = await get_balance(message.from_user.id)
    if bal < cost:
        await message.answer(f"❌ Нужно *{cost} тк.* · У тебя *{bal} тк.*", parse_mode="Markdown", reply_markup=profile_kb())
        return
    await state.set_state(State_.waiting_image)
    await state.update_data(image_model="video", cost=cost)
    await message.answer(
        f"🎬 *Seedance 2.0*  ·  💎 {cost} токенов\n\n"
        f"Выбери формат видео:",
        parse_mode="Markdown", reply_markup=aspect_kb()
    )
@router.message(F.text == "🔊 Озвучить текст")
async def tts_start(message: Message, state: FSMContext):
    cost = 20
    bal  = await get_balance(message.from_user.id)
    if bal < cost:
        await message.answer(f"❌ Нужно *{cost} тк.* · У тебя *{bal} тк.*", parse_mode="Markdown", reply_markup=profile_kb())
        return
    await state.set_state(State_.waiting_image)
    await state.update_data(image_model="tts", cost=cost)
    await message.answer(
        f"🔊 *ElevenLabs TTS*  ·  💎 {cost} токенов\n\n"
        f"Введи текст который хочешь озвучить:\n\n"
        f"Пример: *Привет! Добро пожаловать в AuraAI*",
        parse_mode="Markdown", reply_markup=cancel_kb()
    )
@router.message(F.text == "🎥 Создать видео Kling")
async def kling_generate(message: Message, state: FSMContext):
    cost = 400
    bal  = await get_balance(message.from_user.id)
    if bal < cost:
        await message.answer(f"❌ Нужно *{cost} тк.* · У тебя *{bal} тк.*", parse_mode="Markdown", reply_markup=profile_kb())
        return
    await state.set_state(State_.waiting_image)
    await state.update_data(image_model="kling", cost=cost)
    await message.answer(
        f"🎥 *Kling 1.6*  ·  💎 {cost} токенов\n\n"
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
        await message.answer(f"❌ Нужно *{cost} тк.* · У тебя *{bal} тк.*", parse_mode="Markdown", reply_markup=profile_kb())
        return
    await state.set_state(State_.waiting_photo)
    await state.update_data(cost=cost)
    await message.answer(
        "✏️ *Редактировать фото*  ·  💎 70 токенов\n\n"
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
        await message.answer("❌ Недостаточно токенов.", reply_markup=profile_kb())
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
            f"💎 Потрачено: *{cost} тк.* · Остаток: *{bal} тк.*\n\n"
            f"[📥 Скачать в высоком качестве]({result_url})",
            parse_mode="Markdown",
            disable_web_page_preview=False
        )
        # Сохраняем результат для продолжения редактирования
        user_last_edited[message.from_user.id] = result_url
        # Инфо и ссылка отдельным сообщением
        await message.answer(
            f"📌 Запрос: _{prompt_text}_\n\n"
            f"💎 Потрачено: *{cost} тк.* · Остаток: *{bal} тк.*\n\n"
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
            await thinking.edit_text("⏱ Время вышло. Токены возвращены.")
        except Exception:
            await message.answer("⏱ Время вышло. Токены возвращены.")
        await message.answer("Попробуй снова:", reply_markup=design_kb())

    except Exception as e:
        await add_credits(message.from_user.id, cost, "bonus", "Возврат: ошибка")
        try:
            await thinking.edit_text(f"⚠️ Ошибка. Токены возвращены.\n{str(e)[:100]}")
        except Exception:
            await message.answer("⚠️ Ошибка. Токены возвращены.")
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
        await message.answer(f"❌ Нужно *{cost} тк.* · У тебя *{bal} тк.*", parse_mode="Markdown", reply_markup=profile_kb())
        return
    await state.set_state(State_.waiting_video_photo)
    await state.update_data(cost=cost)
    await message.answer(
        "🖼➡️🎬 *Фото в видео*  ·  💎 100 токенов\n\n"
        "1️⃣ Отправь фото которое хочешь оживить:",
        parse_mode="Markdown", reply_markup=cancel_kb()
    )

@router.message(State_.waiting_video_photo, F.photo)
async def img2video_photo_received(message: Message, state: FSMContext):
    photo = message.photo[-1]
    file = await message.bot.get_file(photo.file_id)
    file_url = f"https://api.telegram.org/file/bot{message.bot.token}/{file.file_path}"
    user_video_photo_urls[message.from_user.id] = file_url
    await state.set_state(State_.waiting_video_aspect)
    await message.answer(
        "✅ Фото получено!\n\n2️⃣ Выбери формат видео:",
        reply_markup=aspect_kb()
    )

@router.message(State_.waiting_video_aspect, F.text.in_(ASPECT_MAP.keys()))
async def img2video_aspect(message: Message, state: FSMContext):
    await state.update_data(video_aspect=ASPECT_MAP[message.text])
    await state.set_state(State_.waiting_video_photo_text)
    await message.answer(
        f"Формат: {ASPECT_MAP[message.text]} ✅\n\n3️⃣ Опиши что должно происходить в видео:\n\n"
        "Примеры: плавное движение камеры · волосы на ветру · облака плывут",
        reply_markup=cancel_kb()
    )

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
        await message.answer("❌ Недостаточно токенов.", reply_markup=profile_kb())
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
                caption=f"🖼➡️🎬 *Фото в видео*\n\n💎 Потрачено: *{cost} тк.* · Остаток: *{bal} тк.*",
                parse_mode="Markdown"
            )
            await message.answer("Что дальше?", reply_markup=video_kb())
        except Exception as e:
            await add_credits(uid, cost, "bonus", "Возврат: ошибка img2video")
            await message.answer(f"⚠️ Ошибка. Токены возвращены.\n{str(e)[:100]}", reply_markup=video_kb())
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
        await message.answer(f"❌ Нужно минимум *800 тк.* · У тебя *{bal} тк.*", parse_mode="Markdown", reply_markup=profile_kb())
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
        await message.answer(f"❌ Нужно *{m['cost']} тк.* · У тебя *{bal} тк.*", parse_mode="Markdown", reply_markup=profile_kb())
        return
    await state.update_data(avatar_model=m["model"], avatar_label=m["label"], cost=m["cost"])
    await message.answer(
        f"Модель: *{m['label']}* ✅  ·  💎 {m['cost']} тк.\n\n"
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
        await message.answer("❌ Недостаточно токенов.", reply_markup=profile_kb())
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
                caption=f"🗣 *ИИ-аватар готов!* ({label})\n\n💎 Потрачено: *{cost} тк.* · Остаток: *{b} тк.*",
                parse_mode="Markdown"
            )
            await message.answer("Что дальше?", reply_markup=video_kb())
        except Exception as e:
            await add_credits(message.from_user.id, cost, "bonus", "Возврат: ошибка аватара")
            await message.answer(f"⚠️ Ошибка генерации аватара. Токены возвращены.\n{str(e)[:120]}", reply_markup=video_kb())
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
        await message.answer(f"❌ Нужно *{cost} тк.* · У тебя *{bal} тк.*", parse_mode="Markdown", reply_markup=profile_kb())
        return
    await state.set_state(State_.waiting_combine)
    await state.update_data(cost=cost)
    combine_buffer.pop(message.from_user.id, None)
    await message.answer(
        "🔗 *Соединить фото*  ·  💎 70 токенов\n\n"
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
                await message.answer("❌ Недостаточно токенов.", reply_markup=profile_kb())
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
                    f"💎 Потрачено: *{cost} тк.* · Остаток: *{bal} тк.*\n\n"
                    f"[📥 Скачать в высоком качестве]({result_url})",
                    parse_mode="Markdown", disable_web_page_preview=False
                )
                await message.answer("Что дальше?", reply_markup=design_kb())
                await log_request(uid, "combine", "nano-banana-pro-edit", cost)
            except Exception as e:
                await add_credits(uid, cost, "bonus", "Возврат: ошибка соединения")
                await message.answer(f"⚠️ Ошибка. Токены возвращены.\n{str(e)[:100]}", reply_markup=design_kb())
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
        await message.answer(f"❌ Нужно *{cost} тк.* для редактирования фото · У тебя *{bal} тк.*", parse_mode="Markdown")
        return

    ok = await use_credits(message.from_user.id, "img2img_remix", cost)
    if not ok:
        await message.answer("❌ Недостаточно токенов.", reply_markup=profile_kb())
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
            f"💎 Потрачено: *{cost} тк.* · Остаток: *{bal} тк.*\n\n"
            f"[📥 Скачать в высоком качестве]({result_url})",
            parse_mode="Markdown",
            disable_web_page_preview=False
        )
        await message.answer("📸 Отправь ещё фото с подписью для редактирования!", reply_markup=design_kb())
        await log_request(message.from_user.id, "img2img_remix", "nano-banana-pro", cost)
    except Exception as e:
        await add_credits(message.from_user.id, cost, "bonus", "Возврат: ошибка remix")
        await message.answer(f"⚠️ Ошибка. Токены возвращены.\n{str(e)[:100]}", reply_markup=design_kb())
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
        "_Платишь сразу за год, токены зачисляются полностью._\n\n"
        "⭐️ *Basic год — 3 900₽* (вместо 4 680₽)\n• 24 000 токенов\n\n"
        "👑 *Pro год — 10 900₽* (вместо 13 080₽)  🔥\n• 54 000 токенов + скидка 25% на фото\n\n"
        "💎 *Premium год — 22 900₽* (вместо 27 480₽)  ⭐️\n• 108 000 токенов + безлимит чат + скидка 50% на фото\n\n"
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
        "👑 *Подписки AuraAI* (помесячно)\n\n"
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
            title=f"AuraAI — {pack['name']}",
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
            title=f"AuraAI {plan['name']}",
            description=f"{plan['credits']} кредитов на год",
            payload=f"planyear_{item_id}",
            currency="XTR",
            prices=[LabeledPrice(label=plan["name"], amount=plan["stars"])],
        )
    elif kind == "course":
        await callback.bot.send_invoice(
            chat_id=callback.from_user.id,
            title=COURSE["name"],
            description="Доступ к курсу + 1000 токенов",
            payload="course_main",
            currency="XTR",
            prices=[LabeledPrice(label=COURSE["name"], amount=COURSE["stars"])],
        )
    else:
        plan = PLANS.get(item_id)
        if not plan: return
        await callback.bot.send_invoice(
            chat_id=callback.from_user.id,
            title=f"AuraAI {plan['name']} — 30 дней",
            description=plan["description"],
            payload=f"plan_{item_id}",
            currency="XTR",
            prices=[LabeledPrice(label=f"AuraAI {plan['name']}", amount=plan["stars"])],
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
            title=f"AuraAI — {pack['name']}",
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
            title=f"AuraAI {plan['name']}",
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
            description="Доступ к курсу + 1000 токенов",
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
            title=f"AuraAI {plan['name']} — 30 дней",
            description=plan["description"],
            payload=f"plan_{item_id}",
            provider_token=YOOKASSA_TOKEN,
            currency="RUB",
            prices=[LabeledPrice(label=f"AuraAI {plan['name']}", amount=plan["rub"] * 100)],
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

    item_name = "Доступ к сервису AuraAI"
    if payload.startswith("credits_"):
        pack = CREDIT_PACKS.get(payload.replace("credits_", ""))
        if pack:
            item_name = f"AuraAI — {pack['name']}"
            new_bal = await add_credits(uid, pack["credits"], "purchase", f"Покупка: {pack['name']}")
            await message.answer(f"✅ *Оплата прошла!*\n\n💎 +{pack['credits']} кредитов\n💰 Баланс: *{new_bal} тк.*", parse_mode="Markdown", reply_markup=main_kb())
    elif payload.startswith("planyear_"):
        plan = PLANS_ANNUAL.get(payload.replace("planyear_", ""))
        if plan:
            item_name = f"AuraAI {plan['name']}"
            await set_plan(uid, plan["base"], plan["credits"], plan["days"])
            bal = await get_balance(uid)
            await message.answer(f"✅ *{plan['name']} активирован на год!*\n\n💎 +{plan['credits']} кредитов\n💰 Баланс: *{bal} тк.*", parse_mode="Markdown", reply_markup=main_kb())
    elif payload.startswith("plan_"):
        plan = PLANS.get(payload.replace("plan_", ""))
        if plan:
            item_name = f"AuraAI {plan['name']}"
            await set_plan(uid, payload.replace("plan_", ""), plan["credits"], plan["days"])
            bal = await get_balance(uid)
            await message.answer(f"✅ *{plan['name']} активирован!*\n\n💎 +{plan['credits']} кредитов\n💰 Баланс: *{bal} тк.*", parse_mode="Markdown", reply_markup=main_kb())
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
                f"💰 *Реферальная комиссия!*\n\n{info['emoji']} {info['name']} ({commission['percent']}%)\nНачислено: *+{commission['credits_earned']} тк.* и ⭐️ *{commission['stars_earned']}*", parse_mode="Markdown")
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
    await message.answer(f"✅ Начислено *{parts[2]} тк.* Баланс: *{new_bal}*", parse_mode="Markdown")

@router.message(Command("gift"))
async def cmd_gift(message: Message):
    if message.from_user.id != ADMIN_ID: return
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Формат: /gift USER_ID [КОЛИЧЕСТВО]\nНапример: /gift 123456789 300")
        return
    try:
        target = int(parts[1])
        amount = int(parts[2]) if len(parts) > 2 else 300
    except ValueError:
        await message.answer("ID и количество должны быть числами."); return
    user = await get_user(target)
    if not user:
        await message.answer("❌ Этот человек ещё не запускал бота.\nПопроси его открыть бота и нажать /start, затем повтори.")
        return
    new_bal = await add_credits(target, amount, "admin", "Подарок (пробный доступ)")
    await message.answer(f"🎁 Подарено *{amount} тк.* пользователю `{target}`. Его баланс: *{new_bal}*", parse_mode="Markdown")
    try:
        await message.bot.send_message(
            target,
            f"🎁 Тебе подарили *{amount} токенов*!\n\n"
            "Попробуй ИИ-помощника по эмоциональному состоянию: нажми «🧠 Психолог» в меню "
            "и просто напиши, что у тебя на душе. 💛",
            parse_mode="Markdown"
        )
    except Exception:
        await message.answer("⚠️ Кредиты начислены, но уведомление отправить не вышло (человек мог не открывать бота или закрыл личку).")

@router.message(Command("testai"))
async def cmd_testai(message: Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("🔧 Проверяю подключение к ИИ, подожди несколько секунд…")
    lines = ["🔧 Проверка ИИ-провайдеров\n"]
    lines.append(
        f"Ключи в .env: "
        f"Anthropic={'есть' if ANTHROPIC_KEY else 'НЕТ'} · "
        f"DeepSeek={'есть' if DEEPSEEK_KEY else 'НЕТ'} · "
        f"OpenAI={'есть' if OPENAI_KEY else 'НЕТ'}\n"
    )
    clients = {"anthropic": anthropic_client, "deepseek": deepseek_client, "openai": openai_client}
    for model_id, prov in (("claude", "anthropic"), ("deepseek", "deepseek"), ("gpt4o", "openai")):
        if not clients[prov]:
            lines.append(f"• {model_id}: ключ не задан — клиент не создан")
            continue
        try:
            r = await call_text_ai("Ответь одним словом: тест", "Ты — тест.", model_id, timeout_s=20)
            if r and not r.startswith("❌"):
                lines.append(f"• {model_id}: ✅ работает")
            else:
                lines.append(f"• {model_id}: ⚠️ {str(r)[:90]}")
        except Exception as e:
            lines.append(f"• {model_id}: ❌ {str(e)[:160]}")
    await message.answer("\n".join(lines)[:3900])

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
            f"💎 {r['credits']} тк. · {plan_label}\n"
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
        f"💎 Токены: *{user['credits']}*\n"
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



# ====================================================================
#  >>> КОМАНДА ИИ-АГЕНТОВ (Шаг 2) <<<
# ====================================================================
# ══════════════════════════════════════════════════════════════════
#  AuraAI · ВСЯ КОМАНДА ИИ-АГЕНТОВ — ЕДИНАЯ СБОРКА
#  Заменяет: auraai_agent_team / auraai_agent_actions /
#            auraai_finance_agent / auraai_smm_marketer.
#  Вставь ЭТОТ блок один раз среди @router.message(...) в auraai_bot_v3_43.py.
#
#  ──────── ЧТО ВНУТРИ ────────
#   👔 Менеджер  — оркестратор (план + сборка итога)
#   🛠 Инженер   — техника, код, расчёты
#   🤝 Ассистент — тексты, объяснения
#   📣 SMM       — контент + РЕАЛЬНАЯ публикация (TG-канал/Instagram/сторис)
#   📊 Маркетолог— лиды, конверсия, продажи (читает finance_log)
#   💼 Финагент  — приём дневных отчётов + отчётность (прибыль, ROMI)
#
#  ──────── ВСТРОЙКА (2 правки кроме самого блока) ────────
#   [A] в class State_(StatesGroup) добавь 5 строк:
#         agent_menu  = State()
#         agent_auto  = State()
#         agent_solo  = State()
#         finance_menu  = State()
#         finance_input = State()
#   [B] в main_kb() добавь ряд:
#         b.row(KeyboardButton(text="🤖 Команда агентов"))
#       (финансовый агент — только для админа, вход командой /finance)
#
#  Нужные имена из бота (уже есть): router, F, Command, Message, FSMContext,
#   State_, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardBuilder,
#   call_text_ai, use_credits, add_credits, get_balance, log_request,
#   db_run, db_all, main_kb, profile_kb, ADMIN_ID, logging, asyncio, os.
#
#  ──────── ENV для публикаций (по желанию) ────────
#   TG_POST_CHANNEL=@твой_канал          (бот — админ канала; TG-пост работает сразу)
#   TG_BUSINESS_CONNECTION_ID=...        (для сторис: бот как бизнес-бот)
#   IG_USER_ID=... / IG_ACCESS_TOKEN=... (для Instagram; + graph.facebook.com в allow-list)
# ══════════════════════════════════════════════════════════════════

import json, re, datetime, asyncio
from aiogram.types import URLInputFile


# ══════════════════════════════════════════════════════════════════
#  ПРОМПТЫ
# ══════════════════════════════════════════════════════════════════

MANAGER_PLAN_PROMPT = (
    "Ты — Менеджер-оркестратор команды ИИ-агентов AuraAI. Команда работает ВМЕСТЕ над целью пользователя. Состав:\n"
    "• engineer (Инженер) — код, расчёты, технические решения.\n"
    "• assistant (Ассистент) — тексты, объяснения, оформление.\n"
    "• smm (SMM) — контент и РЕАЛЬНАЯ публикация постов/историй в канал.\n"
    "• marketer (Маркетолог) — анализ лидов, конверсии и продаж по данным бизнеса.\n\n"
    "Разбей цель на шаги и задействуй ВСЕХ нужных агентов в правильном порядке "
    "(например: marketer анализирует данные → smm публикует пост на лучшую тему). "
    "Если в контексте есть данные бизнеса — учитывай их.\n"
    "Верни СТРОГО JSON без markdown и пояснений:\n"
    '{"plan":"что делаем","steps":[{"agent":"marketer","task":"..."},{"agent":"smm","task":"опубликуй пост ..."}]}\n'
    "agent — только \"engineer\",\"assistant\",\"smm\" или \"marketer\". Используй несколько агентов, если цель того требует."
)

MANAGER_FINAL_PROMPT = (
    "Ты — Менеджер-оркестратор. Команда выполнила задачу по частям. Собери единый финальный "
    "ответ пользователю: связно, без повторов, готовый к использованию. Не пересказывай, кто "
    "что делал — дай результат."
)

ACTION_AGENT_NOTE = (
    "\n\nЕсли просят ОПУБЛИКОВАТЬ — верни ТОЛЬКО JSON одной строкой, без пояснений:\n"
    '{"action":"tg_post","caption":"текст","image_url":"https://..."}\n'
    '{"action":"tg_story","image_url":"https://...","caption":"текст"}\n'
    '{"action":"ig_post","image_url":"https://...","caption":"текст"}\n'
    "Если фото приложено — image_url можно опустить, подставится само. "
    "Если публиковать не нужно — пиши обычный текст."
)

AGENT_DEFS = {
    "engineer": {
        "emoji": "🛠", "name": "Инженер",
        "prompt": ("Ты — Инженер команды AuraAI. Техническая часть: код, алгоритмы, расчёты, "
                   "архитектура. По делу, с конкретикой и примерами. Кратко и точно."),
    },
    "assistant": {
        "emoji": "🤝", "name": "Ассистент",
        "prompt": ("Ты — Ассистент команды AuraAI. Тексты, понятные объяснения, структура, "
                   "оформление, орг-вопросы. Пиши тепло, ясно, структурно."),
    },
    "smm": {
        "emoji": "📣", "name": "SMM", "can_act": True,
        "prompt": ("Ты — SMM-агент AuraAI. Делаешь контент для соцсетей: посты, сторис, сценарии "
                   "Reels, подписи, хэштеги — коротко, цепляюще, под целевую аудиторию."),
    },
    "marketer": {
        "emoji": "📊", "name": "Маркетолог", "use_data": True,
        "prompt": ("Ты — Маркетолог-аналитик AuraAI. САМ следишь за РЕЗУЛЬТАТОМ, РАСХОДОМ и "
                   "ВОВЛЕЧЁННОСТЬЮ: лиды, конверсия, продажи, выручка, прибыль, ROMI, расходы "
                   "(реклама + прочие), сколько постов вышло и сколько РЕАКЦИЙ они собрали. Цифры "
                   "тебе дают в начале сообщения — анализируй сам. ОСОБОЕ внимание вовлечённости: "
                   "находи, какие посты заходят (много реакций), и рекомендуй ДАВИТЬ на эти темы и "
                   "форматы. Делай выводы: что окупается, где сливается бюджет, как контент влияет "
                   "на продажи; давай 1–3 конкретные рекомендации. Коротко, строго на цифрах."),
    },
}

TEAM_COST_AUTO = 30
TEAM_COST_SOLO = 10


# ══════════════════════════════════════════════════════════════════
#  ОБЩИЕ ХЕЛПЕРЫ
# ══════════════════════════════════════════════════════════════════

def _extract_json(text: str):
    if not text:
        return None
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t).strip()
    s, e = t.find("{"), t.rfind("}")
    if s != -1 and e != -1 and e > s:
        t = t[s:e + 1]
    try:
        d = json.loads(t)
        return d if isinstance(d, dict) else None
    except Exception:
        return None


async def _agent_call(prompt: str, system: str, history_msgs=None, timeout_s: int = 45):
    for mid in ("claude", "gpt4o", "deepseek"):
        try:
            r = await call_text_ai(prompt, system, mid, history_msgs=history_msgs, timeout_s=timeout_s)
            if r and not r.startswith("❌"):
                return r
        except Exception as ex:
            logging.error(f"agent [{mid}] error: {ex}")
    return None


async def _send_block(message, header: str, body: str):
    await message.answer(header, parse_mode="Markdown")
    body = body or "(пусто)"
    for i in range(0, len(body), 3900):
        await message.answer(body[i:i + 3900])


def _money(x):
    return f"{x:,.0f}".replace(",", " ")


# ══════════════════════════════════════════════════════════════════
#  СЛОЙ ДЕЙСТВИЙ (tool-use)
# ══════════════════════════════════════════════════════════════════

GRAPH_VER = "v22.0"


async def dispatch_action(bot, action: dict) -> str:
    a = (action.get("action") or "").lower().strip()
    try:
        if a == "tg_post":
            return await _tg_post(bot, action)
        if a == "tg_story":
            return await _tg_story(bot, action)
        if a == "ig_post":
            return await _ig_post(action)
        return f"⚠️ Неизвестное действие: «{a}»"
    except Exception as e:
        logging.error(f"action {a} error: {e}")
        return f"⚠️ Не удалось выполнить «{a}»: {str(e)[:150]}"


async def _tg_post(bot, action: dict) -> str:
    chat = action.get("chat") or os.getenv("TG_POST_CHANNEL", "") or await get_setting("tg_channel", "")
    if not chat:
        return "⚠️ Не задан канал. Укажи TG_POST_CHANNEL в .env."
    caption = (action.get("caption") or action.get("text") or "")[:1024]
    image_url = action.get("image_url")
    image_prompt = action.get("image_prompt")
    if image_url:
        try:
            await bot.send_photo(chat, URLInputFile(image_url), caption=caption)
            return f"✅ Фото опубликовано в {chat}"
        except Exception as e:
            logging.error(f"tg_post url: {e}")
    try:
        p = image_prompt or caption or "качественная иллюстрация для поста, без текста"
        img = await generate_nano_banana(p, "1:1")
        await bot.send_photo(chat, BufferedInputFile(img, "post.png"), caption=caption)
        return f"✅ Пост с картинкой опубликован в {chat}"
    except Exception as e:
        logging.error(f"tg_post gen: {e}")
    if caption:
        await bot.send_message(chat, caption)
        return f"✅ Пост опубликован в {chat} (без фото)"
    return "⚠️ Нет ни картинки, ни текста."


async def _tg_story(bot, action: dict) -> str:
    bcid = os.getenv("TG_BUSINESS_CONNECTION_ID", "")
    if not bcid:
        return ("⚠️ Сторис в Telegram требует бизнес-подключения: подключи бота к Telegram "
                "Business аккаунту (право управления историями) и задай TG_BUSINESS_CONNECTION_ID.")
    image_url = action.get("image_url")
    if not image_url:
        return "⚠️ Для истории нужен image_url."
    try:
        from aiogram.methods import PostStory
        from aiogram.types import InputStoryContentPhoto
    except ImportError:
        return "⚠️ Нужна aiogram с Bot API 9.0 (postStory). Обнови aiogram."
    await bot(PostStory(
        business_connection_id=bcid,
        content=InputStoryContentPhoto(photo=URLInputFile(image_url)),
        active_period=86400,
        caption=(action.get("caption") or "")[:2048],
    ))
    return "✅ История опубликована в Telegram (24 ч)."


async def _ig_post(action: dict) -> str:
    import httpx
    ig_id = os.getenv("IG_USER_ID", "")
    token = os.getenv("IG_ACCESS_TOKEN", "")
    if not (ig_id and token):
        return ("⚠️ Instagram не настроен: нужны IG_USER_ID и IG_ACCESS_TOKEN "
                "(Business/Creator + Facebook Page + Meta-приложение с instagram_content_publish), "
                "и graph.facebook.com в network allow-list.")
    image_url = action.get("image_url")
    if not image_url:
        return "⚠️ Для поста в Instagram нужен ПУБЛИЧНЫЙ image_url."
    caption = action.get("caption") or ""
    base = f"https://graph.facebook.com/{GRAPH_VER}/{ig_id}"
    async with httpx.AsyncClient(timeout=60) as c:
        r1 = await c.post(f"{base}/media",
                          data={"image_url": image_url, "caption": caption, "access_token": token})
        if r1.status_code >= 400:
            return f"⚠️ Instagram (контейнер): {r1.text[:200]}"
        cid = r1.json().get("id")
        if not cid:
            return f"⚠️ Instagram: нет id контейнера: {r1.text[:150]}"
        await asyncio.sleep(3)
        r2 = await c.post(f"{base}/media_publish",
                          data={"creation_id": cid, "access_token": token})
        if r2.status_code >= 400:
            return f"⚠️ Instagram (публикация): {r2.text[:200]}"
    return "✅ Опубликовано в Instagram."


# ══════════════════════════════════════════════════════════════════
#  ДАННЫЕ ДЛЯ МАРКЕТОЛОГА (читает finance_log)
# ══════════════════════════════════════════════════════════════════

async def marketing_context(days: int = 7) -> str:
    try:
        await db_run("ALTER TABLE finance_log ADD COLUMN sales INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        rows = await db_all(
            "SELECT leads, sales, revenue, ad_spend, payouts FROM finance_log WHERE day >= date('now', ?)",
            (f"-{days - 1} day",)
        )
    except Exception:
        return "Данных по маркетингу пока нет (нужны отчёты через /finance)."
    if not rows:
        return f"За последние {days} дн. данных нет — внеси отчёты через /finance."
    leads = sum(r["leads"] for r in rows)
    sales = sum((r["sales"] or 0) for r in rows)
    rev = sum(r["revenue"] for r in rows)
    ad = sum(r["ad_spend"] for r in rows)
    conv = (sales / leads * 100) if leads else 0
    cpl = (ad / leads) if leads else 0
    check = (rev / sales) if sales else 0
    romi = ((rev - ad) / ad * 100) if ad else 0
    pay = sum(r["payouts"] for r in rows)
    expenses = ad + pay
    profit = rev - expenses
    try:
        await _ensure_posts_table()
        prows = await db_all("SELECT reactions FROM posts_log WHERE day >= date('now', ?)", (f"-{days - 1} day",))
    except Exception:
        prows = []
    nposts = len(prows)
    total_react = sum((p["reactions"] or 0) for p in prows)
    avg_react = (total_react / nposts) if nposts else 0
    return (f"Данные за {days} дн.: лиды {leads}, продажи {sales}, конверсия {conv:.1f}%, "
            f"CPL {_money(cpl)}, средний чек {_money(check)}, выручка {_money(rev)}, "
            f"реклама {_money(ad)}, прочие расходы {_money(pay)}, общий расход {_money(expenses)}, "
            f"прибыль {_money(profit)}, ROMI {romi:.0f}%, постов {nposts}, "
            f"реакций всего {total_react} (в среднем {avg_react:.1f} на пост).")


# ══════════════════════════════════════════════════════════════════
#  КОМАНДА АГЕНТОВ · клавиатуры
# ══════════════════════════════════════════════════════════════════

AUTO_LABEL = "🎯 Вся команда (авто)"
POST_NOW_LABEL = "📰 Пост сейчас"
SWITCH_LABEL = "🔄 Сменить режим"
HOME_LABEL = "🏠 В главное меню"
AGENT_LABELS = {f"{d['emoji']} {d['name']}": role for role, d in AGENT_DEFS.items()}


pending_posts = {}

def _post_confirm_kb(token):
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"pub:{token}"))
    b.row(InlineKeyboardButton(text="🔁 Другой вариант", callback_data=f"redo:{token}"),
          InlineKeyboardButton(text="❌ Отмена", callback_data=f"cxl:{token}"))
    return b.as_markup()

async def _smm_make_post(brief):
    smm_sys = AGENT_DEFS["smm"]["prompt"] + await _smm_brand_note() + (
        "\n\nСделай ОДИН готовый пост для Telegram-канала по брифу ниже — без плейсхолдеров, "
        "конкретный текст с эмодзи и призывом. Верни СТРОГО JSON: "
        '{"caption":"готовый текст поста","image_prompt":"detailed English image prompt, no text on image"}')
    raw = await _agent_call(f"Бриф: {brief}", smm_sys, timeout_s=40)
    d = _extract_json(raw) or {}
    return (d.get("caption") or brief), (d.get("image_prompt") or brief)

async def _preview_post_to(bot, chat_id, caption, image_prompt=None, image_url=None, brief=""):
    import uuid
    token = uuid.uuid4().hex[:12]
    photo_input = None
    if image_url:
        photo_input = URLInputFile(image_url)
    else:
        try:
            img = await generate_nano_banana(image_prompt or caption, "1:1")
            photo_input = BufferedInputFile(img, "preview.png")
        except Exception as e:
            logging.error(f"preview img: {e}")
    fid = None
    cap_preview = ("📝 ЧЕРНОВИК (НЕ опубликован). Нажми «✅ Опубликовать», если ок:\n\n" + (caption or ""))[:1024]
    if photo_input:
        try:
            sent = await bot.send_photo(chat_id, photo_input, caption=cap_preview, reply_markup=_post_confirm_kb(token))
            fid = sent.photo[-1].file_id
        except Exception as e:
            logging.error(f"preview send: {e}")
            await bot.send_message(chat_id, cap_preview, reply_markup=_post_confirm_kb(token))
    else:
        await bot.send_message(chat_id, cap_preview, reply_markup=_post_confirm_kb(token))
    pending_posts[token] = {"caption": caption, "file_id": fid, "image_prompt": image_prompt, "brief": brief}

async def _preview_post(target_msg, uid, caption, image_prompt=None, image_url=None, brief=""):
    await _preview_post_to(target_msg.bot, target_msg.chat.id, caption, image_prompt, image_url, brief)

@router.callback_query(F.data.startswith("pub:"))
async def cb_post_pub(cq):
    token = cq.data.split(":", 1)[1]
    draft = pending_posts.get(token)
    if not draft:
        await cq.answer("Черновик уже обработан", show_alert=True); return
    chat = os.getenv("TG_POST_CHANNEL", "") or await get_setting("tg_channel", "")
    if not chat:
        await cq.message.answer("⚠️ Канал не задан. Команда: /setchannel @канал"); await cq.answer(); return
    try:
        if draft.get("file_id"):
            sent = await cq.message.bot.send_photo(chat, draft["file_id"], caption=(draft["caption"] or "")[:1024])
        else:
            sent = await cq.message.bot.send_message(chat, draft["caption"] or "(пусто)")
        await cq.message.answer(f"✅ Опубликовано в {chat}")
        await _log_post(draft.get("caption"), getattr(sent, "message_id", None), sent.chat.id)
    except Exception as e:
        await cq.message.answer(f"⚠️ Ошибка публикации: {str(e)[:200]}")
    pending_posts.pop(token, None)
    await cq.answer()

@router.callback_query(F.data.startswith("redo:"))
async def cb_post_redo(cq):
    token = cq.data.split(":", 1)[1]
    brief = (pending_posts.get(token) or {}).get("brief") or "пост про курс AuraAI"
    await cq.answer("Готовлю другой вариант...")
    caption, image_prompt = await _smm_make_post(brief)
    await _preview_post_to(cq.message.bot, cq.message.chat.id, caption, image_prompt, brief=brief)

@router.callback_query(F.data.startswith("cxl:"))
async def cb_post_cancel(cq):
    token = cq.data.split(":", 1)[1]
    pending_posts.pop(token, None)
    await cq.message.answer("❌ Пост отменён — в канал НЕ опубликован.")
    await cq.answer()

async def fetch_ai_news(n=6):
    import httpx, xml.etree.ElementTree as ET
    url = ("https://news.google.com/rss/search?q=artificial+intelligence+OR+"
           "%D0%B8%D1%81%D0%BA%D1%83%D1%81%D1%81%D1%82%D0%B2%D0%B5%D0%BD%D0%BD%D1%8B%D0%B9+"
           "%D0%B8%D0%BD%D1%82%D0%B5%D0%BB%D0%BB%D0%B5%D0%BA%D1%82&hl=ru&gl=RU&ceid=RU:ru")
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as c:
            r = await c.get(url, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
        root = ET.fromstring(r.text)
        items = []
        for it in root.iter("item"):
            t = (it.findtext("title") or "").strip()
            l = (it.findtext("link") or "").strip()
            if t and l:
                items.append({"title": t, "link": l})
            if len(items) >= n:
                break
        return items
    except Exception as e:
        logging.error(f"fetch_ai_news: {e}")
        return []

async def _make_news_post():
    import random
    news = await fetch_ai_news(6)
    if not news:
        return None
    item = random.choice(news)
    sys = (AGENT_DEFS["smm"]["prompt"] + await _smm_brand_note() +
        "\n\nНапиши короткий НОВОСТНОЙ пост для Telegram на основе новости про ИИ ниже: 1-2 абзаца, "
        "эмодзи, мысль «ИИ уже делает крутые вещи», и мягко свяжи с тем, что в нашем боте тоже можно "
        "пользоваться ИИ. В конце ОБЯЗАТЕЛЬНО дай ссылку на источник (ИМЕННО присланную) и ссылку на бот. "
        "Верни СТРОГО JSON: "
        '{"caption":"текст со ссылкой на источник","image_prompt":"english image prompt, no text on image"}')
    raw = await _agent_call(f"Новость: {item['title']}\nСсылка источника: {item['link']}", sys, timeout_s=40)
    d = _extract_json(raw) or {}
    cap = d.get("caption") or f"🤖 {item['title']}\n\nИсточник: {item['link']}\n\nПопробуй ИИ сам: https://t.me/{BOT_USERNAME}"
    if item["link"] not in cap:
        cap += f"\n\n🔗 Источник: {item['link']}"
    return cap, (d.get("image_prompt") or "AI technology news, futuristic minimal illustration, no text")

async def _autopublish(bot, caption, image_prompt):
    chat = os.getenv("TG_POST_CHANNEL", "") or await get_setting("tg_channel", "")
    if not chat:
        logging.error("autopost: канал не задан"); return
    try:
        img = await generate_nano_banana(image_prompt or caption, "1:1")
        sent = await bot.send_photo(chat, BufferedInputFile(img, "post.png"), caption=(caption or "")[:1024])
        await _log_post(caption, getattr(sent, "message_id", None), sent.chat.id)
    except Exception as e:
        logging.error(f"autopublish: {e}")

AUTOPOST_PER_DAY = 5

def start_autoposter(bot):
    import random
    async def loop():
        await asyncio.sleep(60)
        interval = max(300, 24 * 3600 // AUTOPOST_PER_DAY)
        while True:
            try:
                mode = await get_setting("autopost", "off")
                if mode in ("approve", "auto"):
                    if random.random() < 0.6:
                        res = await _make_news_post()
                    else:
                        topic = await suggest_autopost_topic([]) or "польза курса AuraAI"
                        res = await _smm_make_post(topic)
                    if res:
                        cap, iprompt = res
                        if mode == "auto":
                            await _autopublish(bot, cap, iprompt)
                        else:
                            await _preview_post_to(bot, ADMIN_ID, cap, iprompt, brief="")
            except Exception as e:
                logging.error(f"autopost loop: {e}")
            await asyncio.sleep(interval)
    asyncio.create_task(loop())

@router.message(Command("autopost"))
async def autopost_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = (message.text or "").split(maxsplit=1)
    arg = parts[1].strip().lower() if len(parts) > 1 else ""
    if arg in ("on", "approve"):
        await set_setting("autopost", "approve")
        await message.answer("✅ Автопостинг ВКЛ (5 в день). Черновики придут тебе на подтверждение кнопкой ✅.")
    elif arg == "auto":
        await set_setting("autopost", "auto")
        await message.answer("✅ Автопостинг ВКЛ в режиме АВТО (5 в день, сразу в канал без подтверждения).")
    elif arg == "off":
        await set_setting("autopost", "off")
        await message.answer("⏹ Автопостинг ВЫКЛ.")
    else:
        cur = await get_setting("autopost", "off")
        await message.answer(f"Текущий режим: {cur}\n\n/autopost on — 5/день с подтверждением\n/autopost auto — 5/день сразу\n/autopost off — выключить")


async def suggest_autopost_topic(recent=None) -> str:
    recent = recent or []
    try:
        stats = await marketing_context(7)
    except Exception:
        stats = ""
    avoid = ("Не повторяй темы: " + "; ".join(recent[-5:]) + ". ") if recent else ""
    sys = AGENT_DEFS["marketer"]["prompt"] + (
        "\n\nНа основе данных предложи ОДНУ тему поста, которая сейчас лучше всего сработает на продажи. "
        'Верни СТРОГО JSON: {"topic":"короткая тема поста"}')
    try:
        raw = await _agent_call(f"{stats}\n{avoid}Предложи тему поста.", sys, timeout_s=40)
        d = _extract_json(raw) or {}
        return (d.get("topic") or "").strip()
    except Exception as e:
        logging.error(f"suggest topic: {e}")
        return ""


async def _post_now(message: Message):
    status = await message.answer("📊 Маркетолог выбирает тему по конверсии...")
    topic = await suggest_autopost_topic([])
    if not topic:
        topic = "польза курса AuraAI: как новичку начать зарабатывать на ИИ-картинках"
    try:
        await status.edit_text(f"📊 Маркетолог выбрал тему: {topic}\n📣 SMM готовит пост...")
    except Exception:
        pass
    caption, image_prompt = await _smm_make_post(topic)
    try:
        await status.delete()
    except Exception:
        pass
    await message.answer(f"📊 *Маркетолог:* лучшая тема сейчас — _{topic}_", parse_mode="Markdown")
    await _preview_post(message, message.from_user.id, caption, image_prompt, brief=topic)


def team_menu_kb(is_admin: bool = False) -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.row(KeyboardButton(text=AUTO_LABEL))
    if is_admin:
        b.row(KeyboardButton(text=POST_NOW_LABEL))
    for label in AGENT_LABELS:
        b.row(KeyboardButton(text=label))
    b.row(KeyboardButton(text=HOME_LABEL))
    return b.as_markup(resize_keyboard=True)


def team_work_kb() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.row(KeyboardButton(text=SWITCH_LABEL))
    b.row(KeyboardButton(text=HOME_LABEL))
    return b.as_markup(resize_keyboard=True)


# ══════════════════════════════════════════════════════════════════
#  КОМАНДА АГЕНТОВ · вход и выбор режима
# ══════════════════════════════════════════════════════════════════

@router.message(Command("team"))
async def team_entry_cmd(message: Message, state: FSMContext):
    await _team_menu(message, state)


@router.message(F.text == "🤖 Команда агентов")
async def team_entry_btn(message: Message, state: FSMContext):
    await _team_menu(message, state)


async def _team_menu(message: Message, state: FSMContext):
    await state.set_state(State_.agent_menu)
    roles = " · ".join(f"{d['emoji']} {d['name']}" for d in AGENT_DEFS.values())
    await message.answer(
        "🤖 *Команда ИИ-агентов*\n\n"
        f"🎯 *Вся команда* — пиши цель, агенты работают вместе ({TEAM_COST_AUTO} тк.)\n"
        f"Или напиши напрямую агенту ({TEAM_COST_SOLO} тк./сообщение):\n{roles}\n\n"
        "Выбери режим 👇",
        parse_mode="Markdown", reply_markup=team_menu_kb(message.from_user.id == ADMIN_ID)
    )


@router.message(State_.agent_menu)
async def team_menu_choose(message: Message, state: FSMContext):
    txt = message.text or ""
    if txt == HOME_LABEL:
        await state.clear()
        await message.answer("Главное меню", reply_markup=main_kb()); return
    if txt == POST_NOW_LABEL:
        if message.from_user.id != ADMIN_ID:
            await message.answer("Эта кнопка только для админа."); return
        await _post_now(message); return
    if txt == AUTO_LABEL:
        await state.set_state(State_.agent_auto)
        await state.update_data(team_transcript=[])
        await message.answer("🎯 *Вся команда подключена.*\nНапиши цель — сделаем вместе 👇",
                             parse_mode="Markdown", reply_markup=team_work_kb()); return
    if txt in AGENT_LABELS:
        role = AGENT_LABELS[txt]
        agent = AGENT_DEFS[role]
        await state.set_state(State_.agent_solo)
        await state.update_data(current_agent=role, solo_history=[])
        await message.answer(f"{agent['emoji']} *{agent['name']}* на связи. Пиши 👇",
                             parse_mode="Markdown", reply_markup=team_work_kb()); return
    await message.answer("Выбери режим кнопкой ниже 👇", reply_markup=team_menu_kb(message.from_user.id == ADMIN_ID))


# ══════════════════════════════════════════════════════════════════
#  РЕЖИМ 1 · АВТО-ОРКЕСТР
# ══════════════════════════════════════════════════════════════════

@router.message(State_.agent_auto)
async def team_auto(message: Message, state: FSMContext):
    txt = message.text or ""
    if txt == HOME_LABEL:
        await state.clear()
        await message.answer("Главное меню", reply_markup=main_kb()); return
    if txt == SWITCH_LABEL:
        await _team_menu(message, state); return

    task = (message.text or message.caption or "").strip()
    if not task:
        await message.answer("Напиши задачу текстом 🙏", reply_markup=team_work_kb()); return

    if not await use_credits(message.from_user.id, "team", TEAM_COST_AUTO):
        await message.answer("❌ Недостаточно токенов.", reply_markup=profile_kb()); return

    data = await state.get_data()
    transcript = data.get("team_transcript", [])
    ctx = ("Контекст прошлой работы:\n" + "\n".join(transcript[-6:]) + "\n\n") if transcript else ""
    try:
        _mkt = await marketing_context(7)
        if _mkt.startswith("Данные за"):
            ctx = f"Данные бизнеса: {_mkt}\n\n" + ctx
    except Exception:
        pass

    status = await message.answer("👔 Менеджер разбирает задачу...")
    plan_raw = await _agent_call(f"{ctx}Задача: {task}", MANAGER_PLAN_PROMPT, timeout_s=40)
    plan = _extract_json(plan_raw)
    if not plan or not isinstance(plan.get("steps"), list) or not plan["steps"]:
        plan = {"plan": "Разберём силами инженера и ассистента.",
                "steps": [{"agent": "engineer", "task": task}, {"agent": "assistant", "task": task}]}
    try:
        await status.edit_text(f"👔 *Менеджер:* {plan.get('plan', '')}", parse_mode="Markdown")
    except Exception:
        pass

    work_log = []
    smm_drafts = []
    for step in plan["steps"][:3]:
        role = step.get("agent")
        agent = AGENT_DEFS.get(role)
        if not agent:
            continue
        sub = step.get("task", task)
        prior = "\n\n".join(work_log) if work_log else "(пока ничего)"
        extra = (await marketing_context() + "\n\n") if agent.get("use_data") else ""
        system = agent["prompt"] + (ACTION_AGENT_NOTE if agent.get("can_act") else "")
        if role == "smm":
            system += await _smm_brand_note()
        prompt = f"{extra}{ctx}Общая задача: {task}\n\nТвоя подзадача: {sub}\n\nЧто сделали коллеги:\n{prior}"
        await message.answer(f"{agent['emoji']} *{agent['name']} работает...*", parse_mode="Markdown")
        reply = await _agent_call(prompt, system, timeout_s=50) or "(нет ответа)"

        if agent.get("can_act"):
            cmd = _extract_json(reply)
            if role == "smm":
                if isinstance(cmd, dict):
                    cap = cmd.get("caption") or reply
                    iprompt = cmd.get("image_prompt") or cap
                else:
                    cap, iprompt = reply, reply
                smm_drafts.append({"caption": cap, "image_prompt": iprompt})
                work_log.append(f"{agent['name']}: подготовил пост (ждёт подтверждения)")
                await _send_block(message, f"{agent['emoji']} *{agent['name']}* подготовил пост:", cap)
                continue
            if isinstance(cmd, dict) and cmd.get("action"):
                if cmd.get("action") in ("tg_post", "tg_story", "ig_post"):
                    smm_drafts.append({"caption": cmd.get("caption") or reply,
                                       "image_prompt": cmd.get("image_prompt") or cmd.get("caption") or reply})
                    work_log.append(f"{agent['name']}: подготовил пост (ждёт подтверждения)")
                else:
                    result = await dispatch_action(message.bot, cmd)
                    await message.answer(f"{agent['emoji']} {result}")
                    work_log.append(f"{agent['name']}: {result}")
                continue
        work_log.append(f"{agent['name']}: {reply}")
        await _send_block(message, f"{agent['emoji']} *{agent['name']}*", reply)

    await message.answer("👔 *Менеджер собирает итог...*", parse_mode="Markdown")
    final = await _agent_call(
        f"Задача: {task}\n\nРабота команды:\n" + "\n\n".join(work_log) + "\n\nСобери итог.",
        MANAGER_FINAL_PROMPT, timeout_s=50)
    if final:
        await _send_block(message, "✅ *Итог от Менеджера*", final)
    else:
        final = work_log[-1] if work_log else ""

    if smm_drafts:
        d0 = smm_drafts[-1]
        await _preview_post(message, message.from_user.id, d0["caption"], d0["image_prompt"])

    try:
        await log_request(message.from_user.id, "team", "claude", TEAM_COST_AUTO)
    except Exception:
        pass
    transcript += [f"Задача: {task}", f"Итог: {final[:500]}"]
    await state.update_data(team_transcript=transcript[-10:])
    bal = await get_balance(message.from_user.id)
    await message.answer(f"💎 Потрачено: *{TEAM_COST_AUTO} тк.* · Остаток: *{bal} тк.*\n\n"
                         "Дай следующую задачу или смени режим 👇",
                         parse_mode="Markdown", reply_markup=team_work_kb())


# ══════════════════════════════════════════════════════════════════
#  РЕЖИМ 2 · ПРЯМОЙ ДИАЛОГ С АГЕНТОМ
# ══════════════════════════════════════════════════════════════════

@router.message(State_.agent_solo)
async def team_solo(message: Message, state: FSMContext):
    txt = message.text or ""
    if txt == HOME_LABEL:
        await state.clear()
        await message.answer("Главное меню", reply_markup=main_kb()); return
    if txt == SWITCH_LABEL:
        await _team_menu(message, state); return

    user_msg = (message.text or message.caption or "").strip()
    if not user_msg:
        await message.answer("Напиши сообщение 🙏", reply_markup=team_work_kb()); return

    data = await state.get_data()
    role = data.get("current_agent")
    agent = AGENT_DEFS.get(role)
    if not agent:
        await _team_menu(message, state); return

    if not await use_credits(message.from_user.id, "team_solo", TEAM_COST_SOLO):
        await message.answer("❌ Недостаточно токенов.", reply_markup=profile_kb()); return

    # приложенное фото → image_url для возможной публикации
    attached_img = None
    if message.photo:
        ph = message.photo[-1]
        f = await message.bot.get_file(ph.file_id)
        attached_img = f"https://api.telegram.org/file/bot{message.bot.token}/{f.file_path}"

    history = data.get("solo_history", [])
    thinking = await message.answer(f"{agent['emoji']} {agent['name']} думает...")

    extra = (await marketing_context() + "\n\n") if agent.get("use_data") else ""
    system = agent["prompt"] + (ACTION_AGENT_NOTE if agent.get("can_act") else "")
    if role == "smm":
        system += await _smm_brand_note()
    reply = await _agent_call(extra + user_msg, system, history_msgs=history, timeout_s=45)

    try:
        await thinking.delete()
    except Exception:
        pass

    if not reply:
        await add_credits(message.from_user.id, TEAM_COST_SOLO, "bonus", "Возврат: ошибка агента")
        await message.answer("Не получилось ответить, токены возвращены 🙏",
                             reply_markup=team_work_kb()); return

    acted = False
    if agent.get("can_act"):
        cmd = _extract_json(reply)
        if role == "smm":
            cap = (cmd.get("caption") if isinstance(cmd, dict) else None) or reply
            iprompt = (cmd.get("image_prompt") if isinstance(cmd, dict) else None) or cap
            await _preview_post(message, message.from_user.id, cap, iprompt, image_url=attached_img, brief=cap)
            acted = True
        elif isinstance(cmd, dict) and cmd.get("action"):
            if cmd.get("action") in ("tg_post", "tg_story", "ig_post"):
                await _preview_post(message, message.from_user.id,
                                    cmd.get("caption") or reply,
                                    cmd.get("image_prompt") or cmd.get("caption") or reply,
                                    image_url=(attached_img or cmd.get("image_url")))
            else:
                result = await dispatch_action(message.bot, cmd)
                await message.answer(f"{agent['emoji']} {result}", reply_markup=team_work_kb())
            acted = True
    if not acted:
        await _send_block(message, f"{agent['emoji']} *{agent['name']}*", reply)

    history += [{"role": "user", "content": user_msg}, {"role": "assistant", "content": reply}]
    await state.update_data(solo_history=history[-12:])
    try:
        await log_request(message.from_user.id, "team_solo", "claude", TEAM_COST_SOLO)
    except Exception:
        pass
    bal = await get_balance(message.from_user.id)
    await message.answer(f"💎 −{TEAM_COST_SOLO} тк. · Остаток: *{bal} тк.*",
                         parse_mode="Markdown", reply_markup=team_work_kb())


# ══════════════════════════════════════════════════════════════════
#  💼 ФИНАНСОВЫЙ АГЕНТ (только админ, вход: /finance)
# ══════════════════════════════════════════════════════════════════

FINANCE_PARSE_PROMPT = (
    "Ты — финансовый агент. Из текста дневного отчёта вытащи числа и верни СТРОГО JSON без markdown:\n"
    '{"ad_spend":число,"leads":целое,"sales":целое,"revenue":число,"payouts":число,"note":"кратко"}\n'
    "ad_spend — расходы на рекламу; leads — сколько пришло (лидов); sales — сколько ПРОДАЖ (оплат); "
    "revenue — выручка; payouts — что отдали/прочие расходы. Чего нет — ставь 0. Бери только числа."
)

FINANCE_REPORT_PROMPT = (
    "Ты — финансовый директор AuraAI. По готовым сводным цифрам составь короткий деловой отчёт: "
    "итоги, 2–3 наблюдения и 1–2 рекомендации. Без воды. Цифры уже посчитаны — не пересчитывай."
)


async def _ensure_finance_table():
    await db_run("""CREATE TABLE IF NOT EXISTS finance_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT DEFAULT (datetime('now')),
        day TEXT, ad_spend REAL DEFAULT 0, leads INTEGER DEFAULT 0,
        sales INTEGER DEFAULT 0, revenue REAL DEFAULT 0, payouts REAL DEFAULT 0, note TEXT
    )""")
    try:
        await db_run("ALTER TABLE finance_log ADD COLUMN sales INTEGER DEFAULT 0")
    except Exception:
        pass


def _today():
    return datetime.date.today().isoformat()


async def _save_finance(d: dict):
    await _ensure_finance_table()
    await db_run(
        "INSERT INTO finance_log (day,ad_spend,leads,sales,revenue,payouts,note) VALUES (?,?,?,?,?,?,?)",
        (_today(), float(d.get("ad_spend") or 0), int(d.get("leads") or 0), int(d.get("sales") or 0),
         float(d.get("revenue") or 0), float(d.get("payouts") or 0), str(d.get("note") or "")))


async def _finance_agg(days: int) -> dict:
    await _ensure_finance_table()
    if days <= 1:
        rows = await db_all("SELECT ad_spend,leads,sales,revenue,payouts FROM finance_log WHERE day = date('now')")
        label = "сегодня"
    else:
        rows = await db_all("SELECT ad_spend,leads,sales,revenue,payouts FROM finance_log WHERE day >= date('now', ?)",
                            (f"-{days - 1} day",))
        label = f"{days} дней"
    ad = sum(r["ad_spend"] for r in rows); leads = sum(r["leads"] for r in rows)
    sales = sum((r["sales"] or 0) for r in rows); rev = sum(r["revenue"] for r in rows)
    pay = sum(r["payouts"] for r in rows)
    return {"label": label, "n": len(rows), "ad": ad, "leads": leads, "sales": sales,
            "rev": rev, "pay": pay, "profit": rev - ad - pay,
            "romi": ((rev - ad) / ad * 100) if ad else 0,
            "conv": (sales / leads * 100) if leads else 0,
            "cpl": (ad / leads) if leads else 0}


def finance_kb() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.row(KeyboardButton(text="📥 Внести отчёт за сегодня"))
    b.row(KeyboardButton(text="📊 Сегодня"), KeyboardButton(text="📈 7 дней"), KeyboardButton(text="🗓 30 дней"))
    b.row(KeyboardButton(text="🏠 В главное меню"))
    return b.as_markup(resize_keyboard=True)


@router.message(Command("finance"))
async def finance_start(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.set_state(State_.finance_menu)
    await message.answer("💼 *Финансовый агент*\n\n📥 Внеси дневной отчёт свободным текстом — разберу цифры.\n"
                         "📊 Кнопки периодов — построю отчётность с прибылью, конверсией и ROMI.",
                         parse_mode="Markdown", reply_markup=finance_kb())


@router.message(State_.finance_menu)
async def finance_menu(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    txt = message.text or ""
    if txt == "🏠 В главное меню":
        await state.clear()
        await message.answer("Главное меню", reply_markup=main_kb()); return
    if txt == "📥 Внести отчёт за сегодня":
        await state.set_state(State_.finance_input)
        await message.answer("Пришли отчёт. Например:\n_реклама 5000, пришло 30, продаж 8, "
                             "заработали 45000, отдали 12000_", parse_mode="Markdown",
                             reply_markup=finance_kb()); return
    period = {"📊 Сегодня": 1, "📈 7 дней": 7, "🗓 30 дней": 30}.get(txt)
    if period:
        await _send_finance_report(message, period); return
    await message.answer("Выбери действие кнопкой ниже 👇", reply_markup=finance_kb())


@router.message(State_.finance_input)
async def finance_input(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    txt = (message.text or "").strip()
    if txt == "🏠 В главное меню":
        await state.clear()
        await message.answer("Главное меню", reply_markup=main_kb()); return
    if not txt:
        await message.answer("Напиши отчёт текстом 🙏", reply_markup=finance_kb()); return

    thinking = await message.answer("💼 Разбираю цифры...")
    parsed = None
    for mid in ("claude", "gpt4o", "deepseek"):
        try:
            raw = await call_text_ai(txt, FINANCE_PARSE_PROMPT, mid, timeout_s=30)
            parsed = _extract_json(raw)
            if parsed:
                break
        except Exception as e:
            logging.error(f"finance parse [{mid}]: {e}")
    try:
        await thinking.delete()
    except Exception:
        pass
    if not parsed:
        await message.answer("Не разобрал. Проще: «реклама 5000, пришло 30, продаж 8, заработали 45000, отдали 12000».",
                             reply_markup=finance_kb()); return

    await _save_finance(parsed)
    ad = float(parsed.get("ad_spend") or 0); rev = float(parsed.get("revenue") or 0)
    pay = float(parsed.get("payouts") or 0); leads = int(parsed.get("leads") or 0)
    sales = int(parsed.get("sales") or 0)
    await state.set_state(State_.finance_menu)
    await message.answer(f"✅ *Записал за {_today()}:*\n📣 Реклама: {_money(ad)}\n👥 Пришло: {leads}\n"
                         f"🛒 Продаж: {sales}\n💰 Выручка: {_money(rev)}\n📤 Выплаты: {_money(pay)}\n"
                         f"━━━━━━━━\n📈 Прибыль за день: *{_money(rev - ad - pay)}*",
                         parse_mode="Markdown", reply_markup=finance_kb())


async def _send_finance_report(message: Message, days: int):
    agg = await _finance_agg(days)
    if agg["n"] == 0:
        await message.answer("За этот период данных нет. Внеси отчёт 👇", reply_markup=finance_kb()); return
    summary = (f"Период: {agg['label']} ({agg['n']} записей)\nРеклама: {_money(agg['ad'])}\n"
               f"Пришло: {agg['leads']}\nПродаж: {agg['sales']}\nКонверсия: {agg['conv']:.1f}%\n"
               f"Выручка: {_money(agg['rev'])}\nВыплаты: {_money(agg['pay'])}\n"
               f"Прибыль: {_money(agg['profit'])}\nROMI: {agg['romi']:.0f}%\nCPL: {_money(agg['cpl'])}")
    thinking = await message.answer("💼 Готовлю отчёт...")
    narrative = None
    for mid in ("claude", "gpt4o", "deepseek"):
        try:
            narrative = await call_text_ai(f"Цифры за период:\n{summary}\n\nСоставь деловой отчёт.",
                                           FINANCE_REPORT_PROMPT, mid, timeout_s=40)
            if narrative and not narrative.startswith("❌"):
                break
        except Exception as e:
            logging.error(f"finance report [{mid}]: {e}")
    try:
        await thinking.delete()
    except Exception:
        pass
    await message.answer(f"📊 *Финансовый отчёт · {agg['label']}*\n\n{summary}", parse_mode="Markdown")
    if narrative:
        await _send_block(message, "🧠 *Аналитика:*", narrative)
    await message.answer("Что дальше? 👇", reply_markup=finance_kb())


# Авто-итог дня админу (опц.): вызови start_daily_finance_report(bot) при старте.
async def start_daily_finance_report(bot):
    async def loop():
        while True:
            now = datetime.datetime.utcnow()
            target = now.replace(hour=21, minute=0, second=0, microsecond=0)
            if target <= now:
                target += datetime.timedelta(days=1)
            await asyncio.sleep((target - now).total_seconds())
            try:
                agg = await _finance_agg(1)
                if agg["n"]:
                    await bot.send_message(ADMIN_ID, f"🌙 Итоги дня: выручка {_money(agg['rev'])}, "
                                           f"прибыль {_money(agg['profit'])}, конверсия {agg['conv']:.1f}%, "
                                           f"ROMI {agg['romi']:.0f}%.")
            except Exception as e:
                logging.error(f"daily finance: {e}")
    asyncio.create_task(loop())

# ====================================================================
#  <<< КОНЕЦ БЛОКА АГЕНТОВ >>>
# ====================================================================

@router.message(Command("testpost"))
async def testpost_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    chat = os.getenv("TG_POST_CHANNEL", "") or await get_setting("tg_channel", "")
    if not chat:
        await message.answer("⚠️ TG_POST_CHANNEL не задан в .env"); return
    try:
        await message.bot.send_message(chat, "✅ Тест: бот пишет в канал.")
        await message.answer(f"✅ Текст ушёл в {chat}. Пробую фото...")
        img = await generate_nano_banana("минималистичная тестовая иллюстрация", "1:1")
        await message.bot.send_photo(chat, BufferedInputFile(img, "test.png"), caption="✅ Тест фото")
        await message.answer(f"✅ Фото тоже ушло в {chat}. Канал настроен верно!")
    except Exception as e:
        await message.answer(f"⚠️ Ошибка отправки в {chat}:\n{str(e)[:300]}\n\nПроверь: бот — админ канала с правом публикации, и @хендл канала верный.")


async def _ensure_settings_table():
    await db_run("CREATE TABLE IF NOT EXISTS bot_settings (k TEXT PRIMARY KEY, v TEXT)")

async def get_setting(key, default=""):
    await _ensure_settings_table()
    row = await db_get("SELECT v FROM bot_settings WHERE k=?", (key,))
    return row["v"] if row else default

async def set_setting(key, value):
    await _ensure_settings_table()
    await db_run("INSERT INTO bot_settings (k,v) VALUES (?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (key, value))

@router.message(Command("setchannel"))
async def setchannel_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: /setchannel @канал\n(для приватного — числовой ID вида -100...)"); return
    ch = parts[1].strip()
    await set_setting("tg_channel", ch)
    await message.answer(f"✅ Канал для постов сохранён: {ch}\nПроверь командой /testpost")


DEFAULT_BRAND = (
    f"Продукт: AuraAI — Telegram-бот с ИИ-инструментами. Умеет: генерация и обработка фото "
    f"(Nano Banana Pro, GPT Image, DALL-E), оживление фото в видео (Kling/Seedance), музыка, "
    f"озвучка, ИИ-аватар. Монетизация — токены и подписки. Есть курс {COURSE['name']} за "
    f"{COURSE['rub']}₽ (в подарок {COURSE['credits']} кредитов). "
    f"Ссылка на бота: https://t.me/{BOT_USERNAME}"
)

async def get_brand():
    return await get_setting("brand_info", DEFAULT_BRAND)

async def _smm_brand_note():
    return ("\n\nДАННЫЕ О ПРОДУКТЕ (пиши КОНКРЕТНО, НИКОГДА не используй плейсхолдеры "
            "вроде [название] или [ссылка] — бери только реальные данные):\n" + await get_brand() +
            "\nВ каждом посте: цепляющий ЗАГОЛОВОК + реальная ССЫЛКА на бота + призыв к действию.")

@router.message(Command("setbrand"))
async def setbrand_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        cur = await get_brand()
        await message.answer(f"Текущее описание продукта:\n\n{cur}\n\nИзменить: /setbrand <текст>")
        return
    await set_setting("brand_info", parts[1].strip())
    await message.answer("✅ Описание продукта обновлено. Теперь SMM пишет по нему.")


async def _ensure_posts_table():
    await db_run("CREATE TABLE IF NOT EXISTS posts_log (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT DEFAULT (datetime('now')), day TEXT, caption TEXT, msg_id INTEGER, chat_id TEXT, reactions INTEGER DEFAULT 0)")
    for ddl in ("msg_id INTEGER", "chat_id TEXT", "reactions INTEGER DEFAULT 0"):
        try:
            await db_run(f"ALTER TABLE posts_log ADD COLUMN {ddl}")
        except Exception:
            pass

async def _log_post(caption, msg_id=None, chat_id=None):
    try:
        await _ensure_posts_table()
        await db_run("INSERT INTO posts_log (day, caption, msg_id, chat_id, reactions) VALUES (date('now'), ?, ?, ?, 0)",
                     ((caption or "")[:300], msg_id, str(chat_id) if chat_id is not None else None))
    except Exception as e:
        logging.error(f"log_post: {e}")

@router.message_reaction_count()
async def on_reaction_count(event):
    try:
        total = sum(getattr(rc, "total_count", 0) for rc in (event.reactions or []))
        await _ensure_posts_table()
        await db_run("UPDATE posts_log SET reactions=? WHERE msg_id=? AND chat_id=?",
                     (total, event.message_id, str(event.chat.id)))
    except Exception as e:
        logging.error(f"reaction count: {e}")


@router.message(Command("analytics"))
async def analytics_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = (message.text or "").split()
    days = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 7
    status = await message.answer(f"📊 Маркетолог анализирует за {days} дн...")
    stats = await marketing_context(days)
    reply = await _agent_call(stats + "\n\nДай свежий разбор и конкретные рекомендации.", AGENT_DEFS["marketer"]["prompt"], timeout_s=45)
    try:
        await status.delete()
    except Exception:
        pass
    if not reply:
        await message.answer("Не получилось получить разбор, попробуй ещё раз 🙏"); return
    await message.answer(f"📊 Цифры: {stats}")
    await _send_block(message, "📈 *Аналитика от Маркетолога*", reply)


# ====================================================================
#  💰 ФИНАНСЫ БИЗНЕСА (пациенты / выручка / расходы / чистая прибыль)
#  Только админ. Вход: /biz
# ====================================================================

BIZ_PARSE_PROMPT = (
    "Из дневного отчёта бизнеса вытащи числа и верни СТРОГО JSON без markdown:\n"
    '{"patients":целое,"revenue":число,"expenses":число,"expenses_by":{"статья":число},"note":"кратко"}\n'
    "patients — сколько пациентов/клиентов пришло; revenue — выручка; expenses — ОБЩИЕ расходы; "
    "expenses_by — разбивка расходов по статьям (аренда, зарплаты, материалы, реклама, прочее), "
    "если они указаны, иначе пустой объект {}. Чего нет — ставь 0. Бери только числа."
)

BIZ_REPORT_PROMPT = (
    "Ты — финансовый директор бизнеса. По готовым сводным цифрам составь короткий деловой отчёт: "
    "итоги (пациенты, выручка, расходы, ЧИСТАЯ ПРИБЫЛЬ, средний чек), 1-2 наблюдения и 1 рекомендацию. "
    "Без воды. Цифры уже посчитаны — опирайся на них."
)

async def _ensure_biz_table():
    await db_run("""CREATE TABLE IF NOT EXISTS biz_finance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT DEFAULT (datetime('now')),
        day TEXT, patients INTEGER DEFAULT 0,
        revenue REAL DEFAULT 0, expenses REAL DEFAULT 0, exp_json TEXT, note TEXT
    )""")
    try:
        await db_run("ALTER TABLE biz_finance ADD COLUMN exp_json TEXT")
    except Exception:
        pass
    try:
        await db_run("ALTER TABLE biz_finance ADD COLUMN src TEXT")
    except Exception:
        pass

async def _save_biz(d):
    await _ensure_biz_table()
    by = d.get("expenses_by") or {}
    total = float(d.get("expenses") or 0)
    if not total and by:
        try:
            total = sum(float(v) for v in by.values())
        except Exception:
            total = 0
    await db_run("INSERT INTO biz_finance (day, patients, revenue, expenses, exp_json, note, src) VALUES (date('now'), ?, ?, ?, ?, ?, 'manual')",
                 (int(d.get("patients") or 0), float(d.get("revenue") or 0), total,
                  json.dumps(by, ensure_ascii=False), str(d.get("note") or "")))

async def _biz_agg(days):
    await _ensure_biz_table()
    await _ensure_visits_table()
    prev, vp = [], []
    if days <= 1:
        rows = await db_all("SELECT patients, revenue, expenses, exp_json FROM biz_finance WHERE day = date('now') AND COALESCE(src,'') != 'salary'")
        v = await db_all("SELECT doctor, revenue FROM visits WHERE src='shift' AND day = date('now')")
        label = "сегодня"
    else:
        rows = await db_all("SELECT patients, revenue, expenses, exp_json FROM biz_finance WHERE day >= date('now', ?) AND COALESCE(src,'') != 'salary'",
                            (f"-{days - 1} day",))
        prev = await db_all("SELECT revenue, expenses FROM biz_finance WHERE day >= date('now', ?) AND day < date('now', ?) AND COALESCE(src,'') != 'salary'",
                            (f"-{2 * days - 1} day", f"-{days - 1} day"))
        v = await db_all("SELECT doctor, revenue FROM visits WHERE src='shift' AND day >= date('now', ?)",
                         (f"-{days - 1} day",))
        vp = await db_all("SELECT doctor, revenue FROM visits WHERE src='shift' AND day >= date('now', ?) AND day < date('now', ?)",
                          (f"-{2 * days - 1} day", f"-{days - 1} day"))
        label = f"{days} дней"
    # Расходы всегда из biz_finance
    exp = sum(r["expenses"] or 0 for r in rows)
    cats = {}
    for r in rows:
        try:
            for k, val in (json.loads(r["exp_json"]) if r["exp_json"] else {}).items():
                cats[k] = cats.get(k, 0) + float(val)
        except Exception:
            pass

    vrev = sum(r["revenue"] or 0 for r in v)
    vpat = len(v)
    aliases = await _get_aliases()
    pct_map = await _get_doctor_percents()

    if vpat > 0:
        # Есть данные смен — используем ТОЛЬКО их для выручки и пациентов
        rev = vrev
        pat = vpat
    else:
        # Нет данных смен — берём из biz_finance
        rev = sum(r["revenue"] or 0 for r in rows)
        pat = sum(r["patients"] or 0 for r in rows)

    vsalary = sum((r["revenue"] or 0) * pct_map.get(_canon_with(r["doctor"] or "", aliases), 0) / 100 for r in v)
    if vsalary > 0:
        exp += vsalary
        cats["ФОТ врачей"] = cats.get("ФОТ врачей", 0) + vsalary

    # Предыдущий период
    vprev_rev = sum(r["revenue"] or 0 for r in vp)
    if vp:
        prev_rev = vprev_rev
        prev_exp = sum((r["revenue"] or 0) * pct_map.get(_canon_with(r["doctor"], aliases), 0) / 100 for r in vp)
    else:
        prev_rev = sum(r["revenue"] or 0 for r in prev)
        prev_exp = sum(r["expenses"] or 0 for r in prev)

    return {"label": label, "n": vpat or len(rows), "patients": pat, "revenue": rev, "expenses": exp,
            "fot": vsalary, "profit": rev - exp, "check": (rev / pat) if pat else 0, "categories": cats,
            "prev_revenue": prev_rev, "prev_profit": prev_rev - prev_exp, "from_shift": vpat > 0}

def biz_kb():
    b = ReplyKeyboardBuilder()
    b.row(KeyboardButton(text="📥 Внести отчёт за сегодня"))
    b.row(KeyboardButton(text="📊 Сегодня"), KeyboardButton(text="📈 7 дней"), KeyboardButton(text="🗓 30 дней"))
    b.row(KeyboardButton(text="📅 По месяцам"), KeyboardButton(text="📅 Выбрать дату"))
    b.row(KeyboardButton(text="✏️ Удалить последний"), KeyboardButton(text="📄 Выгрузить CSV"))
    b.row(KeyboardButton(text="🔄 Обновить из таблицы"))
    b.row(KeyboardButton(text="🏠 В главное меню"))
    return b.as_markup(resize_keyboard=True)

@router.message(Command("biz"))
async def biz_start(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.set_state(State_.biz_menu)
    await message.answer(
        "💰 *Финансы бизнеса*\n\n"
        "📥 Внеси дневной отчёт свободным текстом — посчитаю пациентов, выручку, расходы и чистую прибыль.\n"
        "📊 Кнопки периодов — отчёт за день / 7 / 30 дней.",
        parse_mode="Markdown", reply_markup=biz_kb())

@router.message(State_.biz_menu, ~F.text.startswith("/"))
async def biz_menu(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    txt = message.text or ""
    if txt == "🏠 В главное меню":
        await state.clear()
        await message.answer("Главное меню", reply_markup=main_kb()); return
    if txt == "📥 Внести отчёт за сегодня":
        await state.set_state(State_.biz_input)
        await message.answer("Пришли отчёт. Например:\n_пришло 12 пациентов, выручка 80000, расходы 30000_",
                             parse_mode="Markdown", reply_markup=biz_kb()); return
    if txt == "✏️ Удалить последний":
        await _ensure_biz_table()
        row = await db_get("SELECT id, day, patients, revenue FROM biz_finance ORDER BY id DESC LIMIT 1")
        if not row:
            await message.answer("Записей нет.", reply_markup=biz_kb()); return
        await db_run("DELETE FROM biz_finance WHERE id=?", (row["id"],))
        await message.answer(f"🗑 Удалён последний отчёт за {row['day']} (пациентов {row['patients']}, "
                             f"выручка {_money(row['revenue'])}). Можешь внести заново.", reply_markup=biz_kb()); return
    if txt == "📄 Выгрузить CSV":
        await _ensure_biz_table()
        rows = await db_all("SELECT day, patients, revenue, expenses, note FROM biz_finance ORDER BY day")
        if not rows:
            await message.answer("Данных нет.", reply_markup=biz_kb()); return
        import io, csv
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["Дата", "Пациенты", "Выручка", "Расходы", "Чистая прибыль", "Заметка"])
        for r in rows:
            w.writerow([r["day"], r["patients"], r["revenue"], r["expenses"],
                        (r["revenue"] - r["expenses"]), r["note"] or ""])
        data = buf.getvalue().encode("utf-8-sig")
        await message.answer_document(BufferedInputFile(data, "biz_finance.csv"),
                                      caption="📄 Выгрузка для бухгалтера (открывается в Excel)")
        return
    if txt == "🔄 Обновить из таблицы":
        await message.answer("🔄 Обновляю данные...")
        await _biz_sync_from_sheet()
        await _sync_visits()
        await message.answer("✅ Обновлено. Жми период (Сегодня / 7 / 30 дней) 👇", reply_markup=biz_kb()); return
    if txt == "📅 Выбрать дату":
        await state.set_state(State_.biz_date)
        await message.answer("Напиши дату в формате ДД.ММ.ГГГГ (например 12.06.2026):", reply_markup=biz_kb()); return
    if txt == "📅 По месяцам":
        await _send_biz_monthly(message); return
    period = {"📊 Сегодня": 1, "📈 7 дней": 7, "🗓 30 дней": 30}.get(txt)
    if period:
        await _send_biz_report(message, period); return
    await message.answer("Выбери действие кнопкой ниже 👇", reply_markup=biz_kb())

@router.message(State_.biz_input, ~F.text.startswith("/"))
async def biz_input(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    txt = (message.text or "").strip()
    if txt == "🏠 В главное меню":
        await state.clear()
        await message.answer("Главное меню", reply_markup=main_kb()); return
    if not txt:
        await message.answer("Напиши отчёт текстом 🙏", reply_markup=biz_kb()); return
    thinking = await message.answer("💰 Считаю...")
    parsed = None
    for mid in ("claude", "gpt4o", "deepseek"):
        try:
            raw = await call_text_ai(txt, BIZ_PARSE_PROMPT, mid, timeout_s=30)
            parsed = _extract_json(raw)
            if parsed:
                break
        except Exception as e:
            logging.error(f"biz parse [{mid}]: {e}")
    try:
        await thinking.delete()
    except Exception:
        pass
    if not parsed:
        await message.answer("Не разобрал. Проще: «пришло 12 пациентов, выручка 80000, расходы 30000».",
                             reply_markup=biz_kb()); return
    await _save_biz(parsed)
    pat = int(parsed.get("patients") or 0); rev = float(parsed.get("revenue") or 0)
    exp = float(parsed.get("expenses") or 0)
    await state.set_state(State_.biz_menu)
    await message.answer(f"✅ *Записал за сегодня:*\n🧑‍⚕️ Пациентов: {pat}\n💰 Выручка: {_money(rev)}\n"
                         f"📤 Расходы: {_money(exp)}\n━━━━━━━━\n📈 Чистая прибыль: *{_money(rev - exp)}*",
                         parse_mode="Markdown", reply_markup=biz_kb())

@router.message(State_.biz_date, ~F.text.startswith("/"))
async def biz_date_input(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    txt = (message.text or "").strip()
    if txt == "🏠 В главное меню":
        await state.clear()
        await message.answer("Главное меню", reply_markup=main_kb(True)); return
    d = _norm_date(txt)
    if not d:
        await message.answer("Не понял дату. Формат: 12.06.2026", reply_markup=biz_kb()); return
    await state.set_state(State_.biz_menu)
    await _send_biz_report_date(message, d)

async def _send_biz_report_date(message, date_iso):
    await _ensure_biz_table()
    await _ensure_visits_table()
    rows = await db_all("SELECT patients, revenue, expenses, exp_json FROM biz_finance WHERE day = ? AND COALESCE(src,'') != 'salary'", (date_iso,))
    v = await db_all("SELECT doctor, revenue FROM visits WHERE src='shift' AND day = ?", (date_iso,))
    if not rows and not v:
        await message.answer(f"За {date_iso} данных нет.", reply_markup=biz_kb()); return
    pat = sum(r["patients"] or 0 for r in rows) + len(v)
    rev = sum(r["revenue"] or 0 for r in rows) + sum((r["revenue"] or 0) for r in v)
    exp = sum(r["expenses"] or 0 for r in rows)
    cats = {}
    for r in rows:
        try:
            for k, vv in (json.loads(r["exp_json"]) if r["exp_json"] else {}).items():
                cats[k] = cats.get(k, 0) + float(vv)
        except Exception:
            pass
    aliases = await _get_aliases()
    pct_map = await _get_doctor_percents()
    vsalary = sum((r["revenue"] or 0) * pct_map.get(_canon_with(r["doctor"], aliases), 0) / 100 for r in v)
    if vsalary > 0:
        exp += vsalary
        cats["ФОТ врачей"] = cats.get("ФОТ врачей", 0) + vsalary
    margin = (rev - exp) / rev * 100 if rev else 0
    cat_str = ""
    if cats:
        top = sorted(cats.items(), key=lambda x: -x[1])[:5]
        cat_str = "\nРасходы по статьям: " + ", ".join(f"{k} {_money(vv)}" for k, vv in top)
    summary = (f"Дата: {date_iso}\nПациентов: {pat}\nВыручка: {_money(rev)}\nРасходы: {_money(exp)}\n"
               f"Чистая прибыль: {_money(rev - exp)}\nРентабельность: {margin:.0f}%\n"
               f"Средний чек: {_money(rev / pat) if pat else _money(0)}{cat_str}")
    await message.answer(f"💰 *Финансы бизнеса · {date_iso}*\n\n{summary}", parse_mode="Markdown", reply_markup=biz_kb())

async def _send_biz_report(message, days):
    await _sync_visits()
    agg = await _biz_agg(days)
    if agg["n"] == 0:
        await message.answer("За этот период данных нет. Внеси отчёт 👇", reply_markup=biz_kb()); return
    revenue = agg["revenue"]
    fot     = agg.get("fot", 0)
    exp_other = agg["expenses"] - fot
    total_exp = agg["expenses"]
    profit  = revenue - total_exp
    margin  = (profit / revenue * 100) if revenue else 0
    # Показываем рост только если у обоих периодов есть реальные данные
    growth = ""
    prev_rev = agg.get("prev_revenue") or 0
    if prev_rev > 0 and revenue > 0:
        dr = (revenue - prev_rev) / prev_rev * 100
        # Убираем аномальные значения (>200% скорее всего нет данных за прошлый период)
        if abs(dr) <= 200:
            growth = f"\nДинамика выручки: {dr:+.0f}% к пред. периоду"
    cats = agg.get("categories") or {}
    cat_lines = ""
    if cats:
        top = sorted(cats.items(), key=lambda x: -x[1])[:5]
        cat_lines = "\nРасходы по статьям:\n" + "\n".join(f"  • {k}: {_money(v)}" for k, v in top)
    src_note = "\n\n📋 Выручка из таблиц «день/ночь». Прочие расходы — ручной ввод («📥 Внести отчёт»)." if agg.get("from_shift") else ""
    fot_line = f"\nФОТ врачей: {_money(fot)}" if fot > 0 else "\nФОТ врачей: не задан (/setpercent)"
    summary = (f"Период: {agg['label']} ({agg['n']} приёмов)\n"
               f"Пациентов: {agg['patients']}\n"
               f"Выручка: {_money(revenue)}\n"
               f"{fot_line}\n"
               f"Прочие расходы: {_money(exp_other)}\n"
               f"Итого расходы: {_money(total_exp)}\n"
               f"Чистая прибыль: {_money(profit)}\n"
               f"Рентабельность: {margin:.0f}%\n"
               f"Средний чек: {_money(agg['check'])}"
               f"{growth}{cat_lines}{src_note}")
    thinking = await message.answer("💰 Готовлю отчёт...")
    narrative = None
    for mid in ("claude", "gpt4o", "deepseek"):
        try:
            narrative = await call_text_ai(f"Цифры за период:\n{summary}\n\nСоставь деловой отчёт.",
                                           BIZ_REPORT_PROMPT, mid, timeout_s=40)
            if narrative and not narrative.startswith("❌"):
                break
        except Exception as e:
            logging.error(f"biz report [{mid}]: {e}")
    try:
        await thinking.delete()
    except Exception:
        pass
    await message.answer(f"💰 *Финансы бизнеса · {agg['label']}*\n\n{summary}", parse_mode="Markdown")
    if narrative:
        await _send_block(message, "🧠 *Аналитика:*", narrative)
    await message.answer("Что дальше? 👇", reply_markup=biz_kb())


async def _biz_period_map():
    await _ensure_biz_table()
    await _ensure_visits_table()
    aliases = await _get_aliases()
    pct = await _get_doctor_percents()
    per = {}

    # Основной источник выручки — shift; clean только для периодов без shift
    v = await db_all("""
        SELECT period, day, doctor, revenue FROM visits WHERE src='shift'
        UNION ALL
        SELECT period, day, doctor, revenue FROM visits WHERE src='clean'
          AND period NOT IN (SELECT DISTINCT period FROM visits WHERE src='shift' AND period IS NOT NULL)
    """)
    days_with_shift = set()
    for r in v:
        p = r["period"] or ((r["day"] or "")[:7]) or "—"
        s = per.setdefault(p, {"rev": 0.0, "fot": 0.0, "exp": 0.0, "n": 0})
        rev = r["revenue"] or 0
        s["rev"] += rev
        s["n"] += 1
        s["fot"] += rev * pct.get(_canon_with(r["doctor"] or "", aliases), 0) / 100
        if r["day"]:
            days_with_shift.add(r["day"])

    # Из biz_finance берём только РАСХОДЫ (не выручку — она уже в visits)
    # Выручку из sheet берём только за дни без данных смен
    bf = await db_all("SELECT day, revenue, expenses, src FROM biz_finance")
    for r in bf:
        src = r["src"] or ""
        if src == "salary":
            continue
        day = r["day"] or ""
        p = day[:7] or "—"
        s = per.setdefault(p, {"rev": 0.0, "fot": 0.0, "exp": 0.0, "n": 0})
        # Выручку добавляем из sheet ТОЛЬКО если нет данных смен за этот день
        if src == "sheet" and day not in days_with_shift:
            s["rev"] += r["revenue"] or 0
        # Расходы берём всегда
        s["exp"] += r["expenses"] or 0
    return per


async def _send_biz_monthly(message):
    await message.answer("💰 Считаю по месяцам...")
    await _biz_sync_from_sheet()
    await _sync_visits()
    await _ensure_biz_table()
    await _ensure_visits_table()
    per = await _biz_period_map()
    if not per:
        await message.answer("Данных нет. Подключи таблицы командой /setshift или внеси отчёт вручную.",
                             reply_markup=biz_kb())
        return
    out = []
    for p in sorted(per.keys(), reverse=True)[:6]:
        s = per[p]
        profit = s["rev"] - s["fot"] - s["exp"]
        block = (f"📅 *{_period_label(p)}*\n"
                 f"Выручка: {_money(s['rev'])} ({s['n']} приёмов)\n"
                 f"ФОТ врачей (%): {_money(s['fot'])}\n")
        if s["exp"]:
            block += f"Прочие расходы: {_money(s['exp'])}\n"
        block += f"Прибыль: {_money(profit)}"
        out.append(block)
    note = ("\n\n📋 Выручка — из таблиц «день/ночь». ФОТ — по процентам врачей "
            "(/setpercent). Прочие расходы — что внесёшь вручную кнопкой «📥 Внести отчёт».")
    await _send_block(message, "💰 *Финансы по месяцам*", "\n\n".join(out) + note)
    ps = await _doctor_periods()
    if ps:
        await message.answer("📅 Открыть конкретный месяц — выбери год:", reply_markup=_biz_year_kb(ps))
    await message.answer("Что дальше? 👇", reply_markup=biz_kb())



def _biz_year_kb(periods):
    b = InlineKeyboardBuilder()
    for y in sorted({p[:4] for p in periods if p and p[0].isdigit()}, reverse=True):
        b.row(InlineKeyboardButton(text=f"📅 {y} год", callback_data=f"byear_{y}"))
    return b.as_markup()


def _biz_month_kb(periods, year):
    b = InlineKeyboardBuilder()
    for p in [x for x in periods if x.startswith(year)]:
        b.row(InlineKeyboardButton(text=_period_label(p), callback_data=f"bmon_{p}"))
    b.row(InlineKeyboardButton(text="◀️ К годам", callback_data="byears"))
    return b.as_markup()


async def _render_biz_month(message, period):
    per = await _biz_period_map()
    s = per.get(period)
    if not s:
        await message.answer(f"За {_period_label(period)} данных нет.", reply_markup=biz_kb())
        return
    profit = s["rev"] - s["fot"] - s["exp"]
    margin = (profit / s["rev"] * 100) if s["rev"] else 0
    txt = (f"💰 *Финансы · {_period_label(period)}*\n\n"
           f"Выручка: {_money(s['rev'])} ({s['n']} приёмов)\n"
           f"ФОТ врачей (%): {_money(s['fot'])}\n")
    if s["exp"]:
        txt += f"Прочие расходы: {_money(s['exp'])}\n"
    txt += f"Чистая прибыль: {_money(profit)}\nРентабельность: {margin:.0f}%"
    await message.answer(txt, parse_mode="Markdown", reply_markup=biz_kb())


@router.callback_query(F.data == "byears")
async def cb_byears(cq: CallbackQuery):
    if cq.from_user.id != ADMIN_ID:
        return
    ps = await _doctor_periods()
    if ps:
        await cq.message.answer("📅 Выбери год:", reply_markup=_biz_year_kb(ps))
    await cq.answer()


@router.callback_query(F.data.startswith("byear_"))
async def cb_byear(cq: CallbackQuery):
    if cq.from_user.id != ADMIN_ID:
        return
    year = cq.data.split("_", 1)[1]
    ps = await _doctor_periods()
    await cq.message.answer(f"📅 {year} — выбери месяц:", reply_markup=_biz_month_kb(ps, year))
    await cq.answer()


@router.callback_query(F.data.startswith("bmon_"))
async def cb_bmon(cq: CallbackQuery):
    if cq.from_user.id != ADMIN_ID:
        return
    period = cq.data.split("_", 1)[1]
    await cq.answer("Считаю...")
    await _render_biz_month(cq.message, period)


# ====================================================================
#  📊 GOOGLE ТАБЛИЦЫ → финансы бизнеса (чтение по ссылке, без паролей)
# ====================================================================

def _sheet_csv_url(url):
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", url)
    if not m:
        return None
    sid = m.group(1)
    g = re.search(r"[#&?]gid=(\d+)", url)
    gid = g.group(1) if g else "0"
    return f"https://docs.google.com/spreadsheets/d/{sid}/export?format=csv&gid={gid}"

def _num(s):
    s = re.sub(r"[^\d.,-]", "", str(s)).replace(" ", "").replace(",", ".")
    try:
        return float(s) if s not in ("", "-", ".") else 0.0
    except Exception:
        return 0.0

def _norm_date(s):
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y", "%Y.%m.%d"):
        try:
            return datetime.datetime.strptime(s, fmt).date().isoformat()
        except Exception:
            pass
    return None

async def _get_sheets():
    raw = await get_setting("biz_sheets", "")
    sheets = []
    if raw:
        try:
            sheets = json.loads(raw)
        except Exception:
            sheets = []
    legacy = await get_setting("biz_sheet_csv", "")
    if legacy and legacy not in sheets:
        sheets.append(legacy)
    return sheets

async def _get_salary_sheets():
    raw = await get_setting("salary_sheets", "")
    try:
        return json.loads(raw) if raw else []
    except Exception:
        return []

async def _fetch_salary_rows(csv_url):
    # Таблица "Зарплата персонала": матрица по дням; берём колонку "расход" по названию.
    import csv as _csv, io
    text, err = await _fetch_csv(csv_url)
    if err:
        return None, err
    rows = list(_csv.reader(io.StringIO(text)))
    months = [("январ", 1), ("феврал", 2), ("март", 3), ("апрел", 4), ("мая", 5), ("май", 5),
              ("июн", 6), ("июл", 7), ("август", 8), ("сентябр", 9), ("октябр", 10), ("ноябр", 11), ("декабр", 12)]
    month = year = None
    for row in rows[:8]:
        for cell in row:
            c = (cell or "").lower()
            for name, num in months:
                if name in c:
                    month = num
                    y = re.search(r"(20\d{2})", c)
                    if y:
                        year = int(y.group(1))
                    break
            if month:
                break
        if month:
            break
    today = datetime.date.today()
    month = month or today.month
    year = year or today.year
    exp_c = None
    date_c = None
    header_idx = -1
    for i, row in enumerate(rows[:15]):
        for j, cell in enumerate(row):
            c = (cell or "").lower().strip()
            if "расход" in c:
                exp_c = j
            elif c in ("дата", "число", "день"):
                date_c = j
        if exp_c is not None:
            header_idx = i
            break
    if exp_c is None:
        return None, "не нашёл колонку «расход» — проверь заголовок таблицы"
    if date_c is None:
        date_c = 0
    out = []
    for row in rows[header_idx + 1:]:
        if date_c >= len(row):
            continue
        daycell = (row[date_c] or "").strip()
        if not re.fullmatch(r"\d{1,2}", daycell):
            continue
        day = int(daycell)
        if not (1 <= day <= 31):
            continue
        try:
            d = datetime.date(year, month, day).isoformat()
        except Exception:
            continue
        exp = _num(row[exp_c]) if exp_c < len(row) else 0
        if exp > 0:
            out.append((d, exp))
    try:
        aliases = await _get_aliases()
        percents = {}
        for hrow in rows[:6]:
            for cell in hrow:
                c = (cell or "").strip()
                pm = re.search(r"(\d{1,3})\s*%", c)
                if pm:
                    nm = re.sub(r"\d{1,3}\s*[-–]?\s*\d{0,3}\s*%.*$", "", c).strip()
                    if len(nm) >= 3:
                        percents[_canon_with(nm, aliases)] = int(pm.group(1))
        if percents:
            cur = await _get_doctor_percents()
            cur.update(percents)
            await set_setting("doctor_percents", json.dumps(cur, ensure_ascii=False))
    except Exception as e:
        logging.error(f"salary percents: {e}")
    return out, None

async def _fetch_csv(csv_url):
    import httpx
    urls = [csv_url]
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", csv_url)
    g = re.search(r"[?&]gid=(\d+)", csv_url)
    if m:
        sid = m.group(1)
        gid = g.group(1) if g else "0"
        urls.append(f"https://docs.google.com/spreadsheets/d/{sid}/gviz/tq?tqx=out:csv&gid={gid}")
    last = "не удалось открыть"
    for u in urls:
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
                r = await c.get(u, headers={"User-Agent": "Mozilla/5.0"})
                r.raise_for_status()
            text = r.text
        except Exception as e:
            last = f"не открылась ({str(e)[:60]})"
            continue
        low = text[:600].lower()
        if "<html" in low or "<!doctype" in low:
            last = "таблица закрыта — открой доступ «Всем, у кого есть ссылка: Читатель»"
            continue
        return text, None
    return None, last

async def _fetch_sheet_rows(csv_url):
    import csv as _csv, io
    text, err = await _fetch_csv(csv_url)
    if err:
        return None, err
    out = []
    for row in _csv.reader(io.StringIO(text)):
        if len(row) < 4:
            continue
        day = _norm_date(row[0])
        if not day:
            continue
        out.append((day, int(_num(row[1])), _num(row[2]), _num(row[3]), row[4] if len(row) > 4 else ""))
    return out, None

async def _biz_sync_from_sheet():
    sheets = await _get_sheets()
    salary = await _get_salary_sheets()
    if not sheets and not salary:
        return None, "Таблицы не заданы. Команда: /setsheet <ссылка> или /setsalary <ссылка>"
    all_rows, sal_rows, errors = [], [], []
    for i, url in enumerate(sheets, 1):
        rows, err = await _fetch_sheet_rows(url)
        if err:
            errors.append(f"таблица {i}: {err}")
        else:
            all_rows.extend(rows)
    for i, url in enumerate(salary, 1):
        rows, err = await _fetch_salary_rows(url)
        if err:
            errors.append(f"зарплата {i}: {err}")
        else:
            sal_rows.extend(rows)
    await _ensure_biz_table()
    await db_run("DELETE FROM biz_finance WHERE src='sheet'")
    await db_run("DELETE FROM biz_finance WHERE src='salary'")
    for (day, patients, revenue, expenses, note) in all_rows:
        await db_run("INSERT INTO biz_finance (day, patients, revenue, expenses, exp_json, note, src) VALUES (?,?,?,?,?,?, 'sheet')",
                     (day, patients, revenue, expenses, "{}", note))
    for (day, expenses) in sal_rows:
        await db_run("INSERT INTO biz_finance (day, patients, revenue, expenses, exp_json, note, src) VALUES (?, 0, 0, ?, '{}', 'Зарплата персонала', 'salary')",
                     (day, expenses))
    return len(all_rows) + len(sal_rows), ("; ".join(errors) if errors else None)

@router.message(Command("setsalary"))
async def setsalary_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        n = len(await _get_salary_sheets())
        await message.answer(f"Таблиц «Зарплата персонала» подключено: {n}.\n\nДобавить:\n"
            "/setsalary <ссылка на «Зарплата персонала»>\n\n"
            "Бот возьмёт из неё РАСХОД по дням (колонка «расход»), месяц определит по заголовку вкладки.\n"
            "Выручка и пациенты при этом берутся из таблиц «день/ночь» (/setshift).\n"
            "Доступ к таблице: «по ссылке: Читатель».")
        return
    url = _sheet_csv_url(parts[1].strip())
    if not url:
        await message.answer("Не похоже на ссылку Google-таблицы.")
        return
    sheets = await _get_salary_sheets()
    if url not in sheets:
        sheets.append(url)
    await set_setting("salary_sheets", json.dumps(sheets))
    await message.answer(f"✅ Таблица зарплаты добавлена (всего: {len(sheets)}). Читаю расход...")
    n, err = await _biz_sync_from_sheet()
    await message.answer((f"⚠️ {err}\n" if err else "") + f"✅ Готово. Смотри /biz (расход подтянется в отчёт).")

@router.message(Command("setsheet"))
async def setsheet_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        n = len(await _get_sheets())
        await message.answer(f"Сейчас подключено таблиц: {n}.\n\nДобавить ещё одну:\n"
                             "/setsheet https://docs.google.com/spreadsheets/d/.../edit\n\n"
                             "В таблице сначала: Настройки доступа → «Всем, у кого есть ссылка: Просмотр».\n"
                             "Колонки: Дата | Пациенты | Выручка | Расходы | Заметка.\n\n"
                             "Список: /sheets · Очистить все: /sheetsclear")
        return
    csv_url = _sheet_csv_url(parts[1].strip())
    if not csv_url:
        await message.answer("Это не похоже на ссылку Google-таблицы. Скопируй её целиком.")
        return
    sheets = await _get_sheets()
    if csv_url not in sheets:
        sheets.append(csv_url)
    await set_setting("biz_sheets", json.dumps(sheets))
    await message.answer(f"✅ Таблица добавлена (всего: {len(sheets)}). Тяну данные...")
    imported, err = await _biz_sync_from_sheet()
    await message.answer((f"⚠️ {err}\n" if err else "") + f"✅ Загружено строк: {imported}. Отчёт: /biz")

@router.message(Command("sheets"))
async def sheets_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    sheets = await _get_sheets()
    if not sheets:
        await message.answer("Таблицы не подключены. Добавь: /setsheet <ссылка>"); return
    lines = "\n".join(f"{i}. …{s[-35:]}" for i, s in enumerate(sheets, 1)) or "—"
    salary = await _get_salary_sheets()
    sal_lines = ("\n\n💼 Зарплата персонала (расход):\n" + "\n".join(f"…{s[-35:]}" for s in salary)) if salary else ""
    await message.answer(f"📊 Таблицы /biz: {len(sheets)}\n{lines}{sal_lines}\n\nУдалить одну: /delsheet N · Очистить все: /sheetsclear")

@router.message(Command("sheetsclear"))
async def sheetsclear_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await set_setting("biz_sheets", "[]")
    await set_setting("biz_sheet_csv", "")
    await set_setting("salary_sheets", "[]")
    await _ensure_biz_table()
    await db_run("DELETE FROM biz_finance WHERE src='sheet'")
    await db_run("DELETE FROM biz_finance WHERE src='salary'")
    await message.answer("🗑 Все таблицы /biz и «Зарплата персонала» отключены (ручные отчёты остались).")

@router.message(Command("bizsync"))
async def bizsync_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("🔄 Тяну данные из таблицы...")
    imported, err = await _biz_sync_from_sheet()
    await message.answer(f"⚠️ {err}" if err else f"✅ Обновлено строк: {imported}. Отчёт: /biz")

def start_biz_sync(bot):
    async def loop():
        await asyncio.sleep(120)
        while True:
            try:
                if await _get_sheets() or await _get_salary_sheets():
                    await _biz_sync_from_sheet()
                if await _get_visit_sheets():
                    await _sync_visits()
            except Exception as e:
                logging.error(f"biz sync loop: {e}")
            await asyncio.sleep(6 * 3600)
    asyncio.create_task(loop())


# ====================================================================
#  👨‍⚕️ ОТЧЁТ ПО ВРАЧАМ (визиты: услуги, первичные/повторные, направления, ЗП)
#  Таблица визитов, колонки по порядку:
#    Дата | Врач | Услуга | Тип | Откуда | Выручка | Процент
#  Тип: первичный/повторный. Откуда: имя врача, который направил (или пусто).
# ====================================================================

async def _ensure_visits_table():
    await db_run("""CREATE TABLE IF NOT EXISTS visits (
        id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT, doctor TEXT, service TEXT,
        kind TEXT, ref_from TEXT, revenue REAL DEFAULT 0, percent REAL DEFAULT 0,
        pay TEXT, src TEXT)""")
    try:
        await db_run("ALTER TABLE visits ADD COLUMN patient TEXT")
    except Exception:
        pass
    for ddl in ("pay TEXT", "src TEXT", "period TEXT"):
        try:
            await db_run(f"ALTER TABLE visits ADD COLUMN {ddl}")
        except Exception:
            pass


def _label_to_period(label):
    """Название вкладки -> 'ГГГГ-ММ'. 'Июнь 2026'/'март 2026'/'ИЮЛЬ 2025' -> '2026-06'. Иначе None."""
    low = (label or "").lower()
    ym = re.search(r"(20\d{2})", low)
    mo = 0
    for i, mn in enumerate(_RU_MONTHS, 1):
        if mn in low:
            mo = i
            break
    if mo and ym:
        return f"{ym.group(1)}-{mo:02d}"
    return None


def _period_label(p):
    """'2026-06' -> 'Июнь 2026'."""
    try:
        y, m = p.split("-")
        return f"{_RU_MONTHS[int(m) - 1].capitalize()} {y}"
    except Exception:
        return p or "—"

async def _get_visit_sheets():
    raw = await get_setting("visit_sheets", "")
    try:
        return json.loads(raw) if raw else []
    except Exception:
        return []

async def _get_shift_sheets():
    raw = await get_setting("shift_sheets", "")
    try:
        return json.loads(raw) if raw else []
    except Exception:
        return []

# ── Исправленный разбор смен (v3.44): сумма из колонки «Оплата», приём не теряется ──
_SHIFT_DATE_RE = re.compile(r"(\d{1,2})\s*[.\-/]\s*(\d{1,2})\s*[.\-/]\s*(\d{4})")
_SHIFT_PNUM_RE = re.compile(r"\d{1,3}[.)]?$")     # 1, 2, 15, "1.", "3)"
_SHIFT_SKIP_RE = re.compile(r"итог|аренд")          # итоги и аренда — не пациенты


def _parse_shift_rows(rows, name_keys):
    """Разбор строк одной вкладки (день/ночь, блоками) ->
    [(date, doctor, service, amount, pay, patient)].
    Сумма берётся из колонки «Оплата (сумма)»; приём не теряется без врача."""
    import datetime as _dt
    cur_doc, cur_date = "", ""
    amount_col, pay_col = 2, 4          # по умолчанию: C — сумма, E — вид оплаты
    out = []
    for row in rows:
        cells = [(c or "").strip() for c in row]
        if not any(cells):
            continue
        joined = " ".join(c for c in cells if c)
        low = joined.lower()
        a0 = cells[0] if cells else ""

        m = _SHIFT_DATE_RE.search(joined)
        if m:
            try:
                cur_date = _dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
            except Exception:
                pass

        is_patient = bool(_SHIFT_PNUM_RE.fullmatch(a0))

        # шапка таблицы: «№ | ФИО… | Оплата (сумма) | Анестезия | Вид оплаты»
        if (not is_patient) and ("оплат" in low) and (("фио" in low) or ("№" in joined) or ("вид оказ" in low)):
            for i, c in enumerate(cells):
                cl = c.lower()
                if "оплата" in cl or "сумма" in cl:
                    amount_col = i
                if "вид оплат" in cl:
                    pay_col = i
            continue

        # заголовок врача со словом «Врач»/«Доктор»
        if (("врач" in low) or ("доктор" in low)) and not is_patient and "аренд" not in low:
            dm = re.search(r"(?:врач|доктор)\s*[-\u2013\u2014:.]*\s*([^,\n]+)", joined, re.IGNORECASE)
            if dm and dm.group(1).strip():
                cand = re.split(r"\s*(?:№|фио|вид оказ|оплат|анестез|сумма)", dm.group(1).strip(),
                                maxsplit=1, flags=re.IGNORECASE)[0].strip()
                if cand and re.search(r"[А-Яа-яЁё]", cand):
                    cur_doc = cand[:40]
            continue

        # заголовок врача без слова «Врач»: короткая строка с именем из справочника
        if not is_patient and not _SHIFT_SKIP_RE.search(low) and not re.search(
                r"услуг|оплат|анестез|вид опл|фио|смена|ночь|наличн|перевод|терминал", low):
            non_empty = [c for c in cells if c]
            if 1 <= len(non_empty) <= 3:
                hit = next((c.strip() for c in non_empty if any(k in c.lower() for k in name_keys)), "")
                if hit:
                    cur_doc = hit[:40]
                    continue

        # строки итогов / аренды — не пациенты
        if not is_patient and _SHIFT_SKIP_RE.search(low):
            continue

        # строка пациента
        if is_patient:
            service = cells[1] if len(cells) > 1 else ""
            amount = 0.0
            if amount_col < len(cells):
                amount = _num(cells[amount_col])
            if amount == 0.0 and len(cells) > 2:
                amount = _num(cells[2])
            pay = ""
            if pay_col < len(cells):
                pc = cells[pay_col]
                if pc and not pc.replace(".", "").replace(",", "").replace(" ", "").isdigit():
                    pay = pc.lower()
            if not service and amount == 0.0:
                continue
            out.append((cur_date or _dt.date.today().isoformat(),
                        cur_doc or "Врач не указан", service, amount, pay, _patient_name(service)))
    return out


async def _fetch_shift_rows(csv_url):
    import csv as _csv, io
    text, err = await _fetch_csv(csv_url)
    if err:
        return None, err
    aliases = await _get_aliases()
    name_keys = [k.lower() for _canon, keys in aliases for k in keys]
    rows = list(_csv.reader(io.StringIO(text)))
    return _parse_shift_rows(rows, name_keys), None


async def _fetch_xlsx(sid):
    """Скачать всю книгу Google-таблицы как xlsx (работает при доступе «по ссылке»)."""
    import httpx
    url = f"https://docs.google.com/spreadsheets/d/{sid}/export?format=xlsx"
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as c:
            r = await c.get(url, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            data = r.content
        if data[:2] == b"PK":
            return data
    except Exception:
        return None
    return None


def _parse_xlsx(data):
    """Разобрать xlsx-книгу -> [(имя_листа, rows)]; только стандартная библиотека."""
    import zipfile, io as _io
    from xml.etree import ElementTree as ET
    M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    try:
        z = zipfile.ZipFile(_io.BytesIO(data))
        names = z.namelist()
    except Exception:
        return None
    shared = []
    if "xl/sharedStrings.xml" in names:
        try:
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.findall(M + "si"):
                shared.append("".join(t.text or "" for t in si.iter(M + "t")))
        except Exception:
            shared = []
    try:
        wb = ET.fromstring(z.read("xl/workbook.xml"))
    except Exception:
        return None
    sh_parent = wb.find(M + "sheets")
    if sh_parent is None:
        return None
    sheets = [(s.get("name") or "", s.get(R + "id")) for s in sh_parent.findall(M + "sheet")]
    rid_target = {}
    if "xl/_rels/workbook.xml.rels" in names:
        try:
            rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
            for rel in rels:
                rid_target[rel.get("Id")] = rel.get("Target")
        except Exception:
            pass

    def col_idx(ref):
        i = 0
        for ch in ref:
            if ch.isalpha():
                i = i * 26 + (ord(ch.upper()) - 64)
            else:
                break
        return i - 1 if i > 0 else 0

    out = []
    for name, rid in sheets:
        target = rid_target.get(rid, "")
        if not target:
            continue
        t = target.replace("\\", "/").lstrip("/")
        cand = []
        if t.startswith("xl/"):
            cand.append(t)
        cand.append("xl/" + t)
        cand.append("xl/" + t.split("xl/")[-1])
        path = next((p for p in cand if p in names), None)
        if not path:
            base = t.split("/")[-1]
            path = next((p for p in names if p.endswith("worksheets/" + base)), None)
        if not path:
            continue
        try:
            sx = ET.fromstring(z.read(path))
        except Exception:
            continue
        sd = sx.find(M + "sheetData")
        rows = []
        if sd is not None:
            for row in sd.findall(M + "row"):
                tmp = {}
                maxc = -1
                for c in row.findall(M + "c"):
                    ci = col_idx(c.get("r") or "")
                    tp = c.get("t")
                    val = ""
                    if tp == "s":
                        v = c.find(M + "v")
                        if v is not None and v.text is not None:
                            try:
                                val = shared[int(v.text)]
                            except Exception:
                                val = ""
                    elif tp == "inlineStr":
                        is_ = c.find(M + "is")
                        if is_ is not None:
                            val = "".join(tt.text or "" for tt in is_.iter(M + "t"))
                    else:
                        v = c.find(M + "v")
                        if v is not None:
                            val = v.text or ""
                    tmp[ci] = val
                    if ci > maxc:
                        maxc = ci
                rows.append([tmp.get(i, "") for i in range(maxc + 1)])
        out.append((name, rows))
    return out


_RU_MONTHS = ["январь", "февраль", "март", "апрель", "май", "июнь",
              "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]


def _recent_month_names(n=14):
    """Названия вкладок-месяцев: текущий и предыдущие n месяцев ('июнь 2026', 'Май 2026' ...)."""
    import datetime as _dt
    today = _dt.date.today()
    y, mo = today.year, today.month
    out = []
    for _ in range(n):
        m = _RU_MONTHS[mo - 1]
        out.append((m, y))
        mo -= 1
        if mo == 0:
            mo = 12
            y -= 1
    return out


async def _gviz_sheet(sid, name):
    """Прочитать вкладку по её НАЗВАНИЮ (без gid) через gviz -> rows или None."""
    import httpx, csv as _csv, io, urllib.parse
    url = (f"https://docs.google.com/spreadsheets/d/{sid}/gviz/tq"
           f"?tqx=out:csv&sheet={urllib.parse.quote(name)}")
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
            r = await c.get(url, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code != 200:
                return None
            text = r.text
    except Exception:
        return None
    low = text[:200].lower()
    if ("google.visualization" in low) or text.strip().startswith("/*") or ("does not exist" in low):
        return None  # такой вкладки нет
    rows = list(_csv.reader(io.StringIO(text)))
    if not any(any((c or "").strip() for c in row) for row in rows):
        return None
    return rows


def _sheet_has_data(rows):
    return any(any((c or "").strip() for c in row) for row in rows)


def _rows_have_text(parsed):
    """Есть ли в распарсенном xlsx кириллический текст (а не только числа)."""
    n = 0
    for _nm, rows in parsed:
        for r in rows:
            for c in r:
                if c and re.search(r"[А-Яа-яЁё]", c):
                    n += 1
                    if n >= 3:
                        return True
    return False


def _xlsx_looks_parseable(parsed):
    """xlsx годен, только если в нём есть строки пациентов: номер в кол.A + текст рядом."""
    pat = 0
    for _nm, rows in parsed:
        for r in rows:
            if r and re.fullmatch(r"\d{1,3}", (r[0] or "").strip()) and len(r) >= 2 \
               and any(re.search(r"[А-Яа-яЁё]", (c or "")) for c in r[1:]):
                pat += 1
                if pat >= 2:
                    return True
    return False


async def _iter_shift_sheets(shift):
    """Все вкладки [(label, rows)] по уже добавленным ссылкам.
    Список вкладок берём из книги (xlsx), а ДАННЫЕ читаем по названию через gviz-CSV
    (надёжное чтение текста). Берём только свежие месяцы — по каждой подключённой книге."""
    import csv as _csv, io
    # множество допустимых названий свежих месяцев в нижнем регистре: 'июнь 2026' ...
    recent = {}
    for m, y in _recent_month_names(15):
        recent[f"{m} {y}".lower()] = (m, y)
    out, seen_sid = [], set()
    for url in shift:
        sm = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", url)
        if not sm:
            text, err = await _fetch_csv(url)
            if not err and text:
                out.append(("ссылка", list(_csv.reader(io.StringIO(text)))))
            continue
        sid = sm.group(1)
        if sid in seen_sid:
            continue
        seen_sid.add(sid)
        sheets = {}
        # узнаём реальные названия вкладок книги
        data = await _fetch_xlsx(sid)
        parsed = _parse_xlsx(data) if data else None
        names_from_book = [nm for nm, _ in parsed if nm] if parsed else []
        # Подбираем вкладки у которых название СОДЕРЖИТ "месяц год"
        # Это позволяет читать "Июнь 2026 ночь", "Июнь 2026 день", "июнь 2026" и т.д.
        targets = [nm for nm in names_from_book
                   if any(key in nm.strip().lower() for key in recent)]
        if targets:
            seen_nm = set()
            for nm in targets:
                k = nm.strip().lower()
                if k in seen_nm:
                    continue
                seen_nm.add(k)
                rows = await _gviz_sheet(sid, nm)
                if rows:
                    sheets[nm] = rows
        else:
            # имена не получили — пробуем сгенерированные варианты
            for m, y in _recent_month_names(15):
                for nm in (f"{m.capitalize()} {y}", f"{m} {y}", f"{m.upper()} {y}"):
                    rows = await _gviz_sheet(sid, nm)
                    if rows:
                        sheets[f"{m.capitalize()} {y}"] = rows
                        break
        # совсем ничего — читаем старые ссылки как CSV
        if not sheets:
            for u2 in shift:
                if sid in u2:
                    text, err = await _fetch_csv(u2)
                    if not err and text:
                        sheets[f"вкладка по ссылке {len(sheets) + 1}"] = list(_csv.reader(io.StringIO(text)))
        for nm, rows in sheets.items():
            out.append((nm, rows))
    return out


async def _fetch_visit_rows(csv_url):
    import csv as _csv, io
    text, err = await _fetch_csv(csv_url)
    if err:
        return None, err
    out = []
    for row in _csv.reader(io.StringIO(text)):
        if len(row) < 6:
            continue
        day = _norm_date(row[0])
        if not day:
            continue
        doctor = (row[1] or "").strip()
        if not doctor:
            continue
        service = (row[2] or "").strip()
        kind = (row[3] or "").strip().lower()
        ref_from = (row[4] or "").strip()
        revenue = _num(row[5])
        percent = _num(row[6]) if len(row) > 6 else 0
        out.append((day, doctor, service, kind, ref_from, revenue, percent))
    return out, None

def _patient_name(text):
    """Достаёт ФИО пациента из ячейки «ФИО + услуга» — ведущие слова с заглавной буквы."""
    t = (text or "").strip()
    if not t:
        return ""
    name_words = []
    for w in re.split(r"\s+", t):
        if re.match(r"^[А-ЯЁA-Z][А-Яа-яЁёA-Za-z.\-]*$", w):
            name_words.append(w.strip("."))
            if len(name_words) >= 3:
                break
        else:
            break
    if name_words:
        return " ".join(name_words)[:40]
    return re.split(r"\s+", t)[0][:40]


def _patient_key(text):
    """Достаёт из ячейки «ФИО + услуга» ключ пациента: фамилия + инициалы (для сопоставления)."""
    t = (text or "").strip()
    if not t:
        return ""
    m = re.match(r"\s*([А-ЯЁA-Z][а-яёa-z]+)\.?\s*((?:[А-ЯЁA-Z]\.?\s*){0,2})", t)
    if m:
        surname = m.group(1)
        initials = re.sub(r"[^А-ЯЁA-Za-z]", "", m.group(2) or "")
        return (surname + initials).lower()
    return re.split(r"[\s.]+", t)[0].lower()

async def _sync_visits():
    clean = await _get_visit_sheets()
    shift = await _get_shift_sheets()
    if not clean and not shift:
        return None, "Таблицы не заданы. /setvisits (простая вкладка) или /setshift (день/ночь)."
    all_rows, errors = [], []
    for i, url in enumerate(clean, 1):
        rows, err = await _fetch_visit_rows(url)
        if err:
            errors.append(f"приёмы {i}: {err}")
        else:
            for (day, doctor, service, kind, ref_from, revenue, percent) in rows:
                per = day[:7] if (day and len(day) >= 7) else None
                all_rows.append((day, doctor, service, kind, ref_from, revenue, percent, "", "clean", "", per))
    # Смены: собрать все приёмы, затем по ФИО определить первичный/повторный и перенаправление
    shift_rows = []
    tabs_info = []
    _akeys = [k.lower() for _c, _ks in (await _get_aliases()) for k in _ks]
    for i, (lbl, rows) in enumerate(await _iter_shift_sheets(shift), 1):
        try:
            parsed = _parse_shift_rows(rows, _akeys)
        except Exception as e:
            errors.append(f"вкладка {lbl}: {str(e)[:50]}"); tabs_info.append((lbl, -1)); continue
        tabs_info.append((lbl, len(parsed)))
        per = _label_to_period(lbl)
        for (day, doctor, service, revenue, pay, patient) in parsed:
            shift_rows.append([day, doctor, service, revenue, pay, _patient_key(service), patient, per])
    try:
        await set_setting("shift_tabs", json.dumps(tabs_info, ensure_ascii=False))
    except Exception:
        pass
    shift_rows.sort(key=lambda r: r[0])  # по дате: кто раньше — тот первичный
    first_doctor = {}
    seen_visit = set()
    for (day, doctor, service, revenue, pay, key, patient, per) in shift_rows:
        kind, ref = "", ""
        if key:
            if key not in first_doctor:
                first_doctor[key] = doctor
                if (key, day) not in seen_visit:
                    kind = "первичный"
                    seen_visit.add((key, day))
            elif (key, day) not in seen_visit:
                kind = "повторный"
                seen_visit.add((key, day))
                if doctor != first_doctor[key]:
                    ref = first_doctor[key]  # пациент перешёл от первого врача к этому
        per2 = per or (day[:7] if (day and len(day) >= 7) else None)
        all_rows.append((day, doctor, service, kind, ref, revenue, 0, pay, "shift", patient, per2))
    await _ensure_visits_table()
    await db_run("DELETE FROM visits")
    for r in all_rows:
        await db_run("INSERT INTO visits (day,doctor,service,kind,ref_from,revenue,percent,pay,src,patient,period) VALUES (?,?,?,?,?,?,?,?,?,?,?)", r)
    return len(all_rows), ("; ".join(errors) if errors else None)

@router.message(Command("setvisits"))
async def setvisits_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        n = len(await _get_visit_sheets())
        await message.answer(f"Таблиц визитов подключено: {n}.\n\nДобавить:\n/setvisits <ссылка на Google-таблицу>\n\n"
            "Колонки по порядку:\nДата | Врач | Услуга | Тип | Откуда | Выручка | Процент\n\n"
            "Тип: первичный / повторный. Откуда: имя врача, который направил (или пусто).\n"
            "Доступ к таблице: «по ссылке: просмотр».\n\nСписок: /visits · Очистить: /visitsclear")
        return
    url = _sheet_csv_url(parts[1].strip())
    if not url:
        await message.answer("Не похоже на ссылку Google-таблицы.")
        return
    sheets = await _get_visit_sheets()
    if url not in sheets:
        sheets.append(url)
    await set_setting("visit_sheets", json.dumps(sheets))
    await message.answer(f"✅ Добавлено (всего: {len(sheets)}). Тяну визиты...")
    n, err = await _sync_visits()
    await message.answer((f"⚠️ {err}\n" if err else "") + f"✅ Загружено визитов: {n}. Отчёт: /doctors")

async def _list_sheet_tabs(sid):
    """Все вкладки таблицы [(gid, name)] без авторизации (через htmlview)."""
    import httpx
    text = ""
    for u in (f"https://docs.google.com/spreadsheets/d/{sid}/htmlview",
              f"https://docs.google.com/spreadsheets/d/{sid}/pubhtml"):
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
                r = await c.get(u, headers={"User-Agent": "Mozilla/5.0"})
                r.raise_for_status()
                text = r.text
            if text:
                break
        except Exception:
            continue
    if not text:
        return []
    pairs = []
    for m in re.finditer(r'#gid=(\d+)"[^>]*>\s*([^<]{1,60}?)\s*<', text):
        pairs.append((m.group(1), m.group(2)))
    if not pairs:
        for m in re.finditer(r'"name"\s*:\s*"([^"]{1,60})"[^}]{0,150}?"gid"\s*:\s*"?(\d+)', text):
            pairs.append((m.group(2), m.group(1)))
    seen = {}
    for g, n in pairs:
        n = re.sub(r"\s+", " ", (n or "")).strip()
        if g not in seen and n and "untitled" not in n.lower():
            seen[g] = n
    return list(seen.items())

async def _expand_shift_csv(shift):
    """По уже добавленным ссылкам вернуть [(csv_url, label)] ВСЕХ вкладок их таблиц."""
    out, seen_sid, seen_u = [], set(), set()
    for url in shift:
        sm = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", url)
        if not sm:
            if url not in seen_u:
                seen_u.add(url); out.append((url, "ссылка"))
            continue
        sid = sm.group(1)
        if sid in seen_sid:
            continue
        seen_sid.add(sid)
        tabs = await _list_sheet_tabs(sid)
        if tabs:
            for gid, name in tabs:
                u = f"https://docs.google.com/spreadsheets/d/{sid}/export?format=csv&gid={gid}"
                if u not in seen_u:
                    seen_u.add(u); out.append((u, f"{name} (gid={gid})"))
        else:
            for u2 in shift:
                if sid in u2 and u2 not in seen_u:
                    seen_u.add(u2); out.append((u2, "вкладка по ссылке"))
    return out

@router.message(Command("setshift"))
async def setshift_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        n = len(await _get_shift_sheets())
        await message.answer(f"Таблиц смен (день/ночь) подключено: {n}.\n\nДобавить:\n"
            "/setshift <ссылка на ЗП день или ЗП ночь>\n\n"
            "Это твои таблицы, где день идёт блоком: сверху «врач - Имя», ниже строки пациентов.\n"
            "Бот возьмёт по каждому врачу смены выручку, число приёмов и виды оплаты.\n"
            "Доступ к таблице: «по ссылке: просмотр». Ссылка ведёт на нужный месяц (вкладку).")
        return
    raw_link = parts[1].strip()
    mm = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", raw_link)
    if not mm:
        await message.answer("Не похоже на ссылку Google-таблицы.")
        return
    sid = mm.group(1)
    sheets = await _get_shift_sheets()
    await message.answer("🔎 Ищу все вкладки таблицы…")
    tabs = await _list_sheet_tabs(sid)
    added = []
    if len(tabs) >= 2:
        for gid, name in tabs:
            u = f"https://docs.google.com/spreadsheets/d/{sid}/export?format=csv&gid={gid}"
            if u not in sheets:
                sheets.append(u)
                added.append(f"{name} (gid={gid})")
        head = f"✅ Нашёл вкладок: {len(tabs)}. Добавил новые:\n• " + ("\n• ".join(added) if added else "(все уже были)")
    else:
        u = _sheet_csv_url(raw_link)
        if u and u not in sheets:
            sheets.append(u)
            added.append("вкладка по ссылке")
        head = ("✅ Добавил вкладку по ссылке." if added else "Эта вкладка уже была.") + \
               "\n(Список всех вкладок автоматически получить не вышло — добавляй каждую вкладку ссылкой с #gid из адресной строки.)"
    await set_setting("shift_sheets", json.dumps(sheets))
    await message.answer(head + f"\n\nВсего вкладок: {len(sheets)}. Читаю…")
    n, err = await _sync_visits()
    await message.answer((f"⚠️ {err}\n" if err else "") + f"✅ Загружено приёмов: {n}.\nОтчёт: /doctors или кнопка «📊 Доктора». Проверка: /diag")

@router.message(Command("visits"))
async def visits_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    clean = await _get_visit_sheets()
    shift = await _get_shift_sheets()
    if not clean and not shift:
        await message.answer("Не подключены. /setvisits (простая вкладка) или /setshift (день/ночь)."); return
    txt = ""
    if shift:
        txt += "📅 Смены (день/ночь):\n" + "\n".join(f"{i}. …{s[-30:]}" for i, s in enumerate(shift, 1)) + "\nУдалить: /delshift N\n\n"
    if clean:
        txt += "📋 Вкладки «Приёмы»:\n" + "\n".join(f"{i}. …{s[-30:]}" for i, s in enumerate(clean, 1)) + "\nУдалить: /delvisits N\n\n"
    txt += "Очистить всё: /visitsclear"
    await message.answer(txt)

@router.message(Command("visitsclear"))
async def visitsclear_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await set_setting("visit_sheets", "[]")
    await set_setting("shift_sheets", "[]")
    await _ensure_visits_table()
    await db_run("DELETE FROM visits")
    await message.answer("🗑 Все таблицы по врачам отключены.")

DEFAULT_ALIASES = [
    ["Шарипов Давлат Зафарович", ["шарипов", "давлат"]],
    ["Мостиева Кристина Алибековна", ["кристина", "мостиева", "алибеков"]],
    ["Кисиев Михаил", ["кисиев"]],
    ["Александров Михаил", ["александров"]],
    ["Бега Балаевич", ["бега"]],
    ["Бибо", ["бибо"]],
]

DEFAULT_PERCENTS = {
    "Александров Михаил": 20,
    "Мостиева Кристина Алибековна": 30,
    "Кисиев Михаил": 25,
    "Бибо": 20,
    "Бега Балаевич": 20,
}

async def _get_aliases():
    raw = await get_setting("doctor_aliases", "")
    try:
        a = json.loads(raw) if raw else []
    except Exception:
        a = []
    return a if a else DEFAULT_ALIASES

def _canon_with(name, aliases):
    n = (name or "").strip().lower()
    if not n:
        return ""
    for canon, keys in aliases:
        if any(k.lower() in n for k in keys):
            return canon
    return (name or "").strip()

async def _get_doctor_percents():
    raw = await get_setting("doctor_percents", "")
    try:
        stored = json.loads(raw) if raw else {}
    except Exception:
        stored = {}
    # заданные вручную проценты (приоритетные) поверх извлечённых из таблиц
    return {**DEFAULT_PERCENTS, **stored}

@router.message(Command("setpercent"))
async def setpercent_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    m = re.match(r"/setpercent\s+(.+?)\s*=\s*(\d{1,3})", message.text or "", re.IGNORECASE)
    if not m:
        cur = await _get_doctor_percents()
        lst = "\n".join(f"• {k}: {v}%" for k, v in cur.items()) or "пока пусто"
        await message.answer(f"Проценты врачей:\n{lst}\n\nЗадать: /setpercent Имя = 40")
        return
    aliases = await _get_aliases()
    name = _canon_with(m.group(1).strip(), aliases)
    cur = await _get_doctor_percents()
    cur[name] = int(m.group(2))
    await set_setting("doctor_percents", json.dumps(cur, ensure_ascii=False))
    await message.answer(f"✅ {name}: {m.group(2)}%")

@router.message(Command("alias"))
async def alias_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    m = re.match(r"/alias\s+(.+?)\s*=\s*(.+)", message.text or "", re.IGNORECASE)
    if not m:
        al = await _get_aliases()
        lst = "\n".join(f"• {c} ← {', '.join(k)}" for c, k in al)
        await message.answer(f"Объединение имён (один человек):\n{lst}\n\nДобавить: /alias Полное Имя = вариант1, вариант2")
        return
    canon = m.group(1).strip()
    keys = [k.strip().lower() for k in m.group(2).split(",") if k.strip()]
    al = await _get_aliases()
    al.append([canon, keys])
    await set_setting("doctor_aliases", json.dumps(al, ensure_ascii=False))
    await message.answer(f"✅ {canon} ← {', '.join(keys)}")

@router.message(Command("dumprows"))
async def dumprows_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    shift = await _get_shift_sheets()
    if not shift:
        await message.answer("Нет таблиц смен. Подключи через /setshift."); return
    expanded = await _iter_shift_sheets(shift)
    out = []
    for ti, (lbl, rows) in enumerate(expanded, 1):
        out.append(f"\n===== ВКЛАДКА {ti}: {lbl} ({len(rows)} строк) =====")
        for ri, row in enumerate(rows[:35], 1):
            cells = " | ".join((c or "").strip() for c in row)
            out.append(f"[{ri}] {cells}")
    text = "\n".join(out) or "пусто"
    for i in range(0, len(text), 3500):
        await message.answer("```\n" + text[i:i + 3500] + "\n```", parse_mode="Markdown")


@router.message(Command("diag"))
async def diag_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("🔧 Проверяю таблицы по очереди…")
    shift = await _get_shift_sheets()
    clean = await _get_visit_sheets()
    lines = [f"🔧 Диагностика\n\nВкладок смен (/setshift): {len(shift)}\nВкладок приёмов (/setvisits): {len(clean)}"]
    expanded = await _iter_shift_sheets(shift)
    lines.append(f"Найдено вкладок в этих таблицах: {len(expanded)}")
    _akeys = [k.lower() for _c, _ks in (await _get_aliases()) for k in _ks]
    for i, (lbl, rows) in enumerate(expanded, 1):
        try:
            parsed = _parse_shift_rows(rows, _akeys)
        except Exception as e:
            lines.append(f"\n{i}) {lbl} — ⚠️ {str(e)[:40]}"); continue
        docs = sorted(set(r[1] for r in parsed))
        lines.append(f"\n{i}) {lbl} — строк: {len(parsed)}\n    врачи: {', '.join(docs[:12]) or '— не найдено'}")
    cnt, serr = await _sync_visits()
    total = await db_get("SELECT COUNT(*) c, MIN(day) a, MAX(day) b FROM visits")
    if total and total["c"]:
        lines.append(f"\n\nИтого в базе: {total['c']} приёмов, даты {total['a']} — {total['b']}")
    else:
        lines.append("\n\nБаза пустая — ни одной строки пациента не прочиталось.")
    lines.append("\n\nℹ️ Бот сам читает все вкладки по уже добавленным ссылкам. Если какой-то вкладки нет в списке выше или врач не распознан — пришли мне пару строк из неё.")
    await message.answer("\n".join(lines)[:3900])

async def _doctor_periods():
    rows = await db_all("SELECT DISTINCT period FROM visits WHERE period IS NOT NULL AND period != '' AND src IN ('shift','clean')")
    return sorted([r["period"] for r in rows if r["period"]], reverse=True)


def _doctor_year_kb(periods):
    b = InlineKeyboardBuilder()
    years = sorted({p[:4] for p in periods}, reverse=True)
    for y in years:
        b.row(InlineKeyboardButton(text=f"📅 {y} год", callback_data=f"dyear_{y}"))
    return b.as_markup()


def _doctor_month_kb(periods, year):
    b = InlineKeyboardBuilder()
    months = [p for p in periods if p.startswith(year)]
    for p in months:
        b.row(InlineKeyboardButton(text=_period_label(p), callback_data=f"dmon_{p}"))
    b.row(InlineKeyboardButton(text="◀️ К годам", callback_data="dyears"))
    return b.as_markup()


@router.callback_query(F.data == "dyears")
async def cb_dyears(cq: CallbackQuery):
    if cq.from_user.id != ADMIN_ID:
        return
    ps = await _doctor_periods()
    if ps:
        await cq.message.answer("📅 Выбери год:", reply_markup=_doctor_year_kb(ps))
    await cq.answer()


@router.callback_query(F.data.startswith("dyear_"))
async def cb_dyear(cq: CallbackQuery):
    if cq.from_user.id != ADMIN_ID:
        return
    year = cq.data.split("_", 1)[1]
    ps = await _doctor_periods()
    await cq.message.answer(f"📅 {year} — выбери месяц:", reply_markup=_doctor_month_kb(ps, year))
    await cq.answer()


@router.callback_query(F.data.startswith("dmon_"))
async def cb_dmon(cq: CallbackQuery):
    if cq.from_user.id != ADMIN_ID:
        return
    period = cq.data.split("_", 1)[1]
    await cq.answer("Готовлю отчёт...")
    DFILTER = "AND doctor IS NOT NULL AND doctor != '' AND doctor != '—' AND LOWER(doctor) NOT LIKE '%не указан%'"
    # shift — основной источник, clean — резерв (если shift нет), zp — крайний резерв
    rows = await db_all(f"SELECT doctor,service,kind,ref_from,revenue,percent,pay,src,patient FROM visits WHERE period=? AND src='shift' {DFILTER}", (period,))
    if not rows:
        rows = await db_all(f"SELECT doctor,service,kind,ref_from,revenue,percent,pay,src,patient FROM visits WHERE period=? AND src='clean' {DFILTER}", (period,))
    if not rows:
        rows = await db_all(f"SELECT doctor,service,kind,ref_from,revenue,percent,pay,src,patient FROM visits WHERE period=? AND src='zp' {DFILTER}", (period,))
    if not rows:
        await cq.message.answer(f"За {_period_label(period)} данных нет.")
        return
    zp_pct = {(r["doctor"] or "").lower(): r["percent"] for r in await db_all("SELECT doctor, percent FROM visits WHERE period=? AND src='zp' AND percent>0", (period,))}
    rows = [{**dict(r), "percent": r["percent"] or zp_pct.get((r["doctor"] or "").lower(), 0)} for r in rows]
    await _render_doctor_detail(cq.message, rows, _period_label(period))


async def _render_doctor_detail(message, rows, period_label):
    aliases = await _get_aliases()
    pct_map = await _get_doctor_percents()
    docs = {}
    sent_to = {}
    for r in rows:
        d = _canon_with(r["doctor"] or "—", aliases)
        x = docs.setdefault(d, {"total": 0, "first": 0, "repeat": 0, "rev": 0.0,
                                "services": {}, "ref_in": 0, "ref_in_by": {}, "salary": 0.0, "pay": {}})
        x["total"] += 1
        k = r["kind"] or ""
        if k.startswith("перв"):
            x["first"] += 1
        elif k.startswith("повт"):
            x["repeat"] += 1
        rev = r["revenue"] or 0
        x["rev"] += rev
        if r["src"] == "clean":
            sv = r["service"] or "—"
            x["services"][sv] = x["services"].get(sv, 0) + rev
        rf = (r["ref_from"] or "").strip()
        rf = _canon_with(rf, aliases) if rf else ""
        if rf:
            x["ref_in"] += 1
            x["ref_in_by"][rf] = x["ref_in_by"].get(rf, 0) + 1
            sent_to.setdefault(rf, {})
            sent_to[rf].setdefault(d, [])
            sent_to[rf][d].append((r["patient"] or "").strip() or "пациент")
        x["salary"] += rev * (r["percent"] or 0) / 100
        p = (r["pay"] or "").strip()
        if p:
            x["pay"][p] = x["pay"].get(p, 0) + rev
    blocks = []
    for d, x in sorted(docs.items(), key=lambda kv: -kv[1]["rev"]):
        lines = [f"Приёмов: {x['total']} · Выручка: {_money(x['rev'])}"]
        if x["first"] or x["repeat"]:
            lines.append(f"Первичных {x['first']}, повторных {x['repeat']}")
        if x["services"]:
            svc = ", ".join(f"{k} {_money(v)}" for k, v in sorted(x["services"].items(), key=lambda kv: -kv[1])[:6])
            lines.append(f"По услугам: {svc}")
        if x["ref_in"]:
            refin = "; ".join(f"от {k} {v}" for k, v in x["ref_in_by"].items())
            lines.append(f"Пришло по направлению: {x['ref_in']} ({refin})")
        if sent_to.get(d):
            tot = sum(len(v) for v in sent_to[d].values())
            to_str = ", ".join(f"к {t} {len(v)}" for t, v in sorted(sent_to[d].items(), key=lambda kv: -len(kv[1])))
            lines.append(f"Направил к другим: {tot} ({to_str})")
        pct = pct_map.get(d)
        salary = x["rev"] * pct / 100 if pct else x["salary"]
        if salary > 0:
            lines.append(f"ЗП по проценту{f' ({pct}%)' if pct else ''}: {_money(salary)}")
        if x["pay"]:
            pays = ", ".join(f"{k} {_money(v)}" for k, v in sorted(x["pay"].items(), key=lambda kv: -kv[1]))
            lines.append(f"Оплата: {pays}")
        blocks.append(f"👨‍⚕️ {d}\n" + "\n".join(lines))
    flows = []
    for a, targets in sent_to.items():
        for b, plist in targets.items():
            names = ", ".join(p for p in plist if p and p != "пациент")
            label = f"от {a} → к {b}: {len(plist)}"
            if names:
                label += f" — {names}"
            flows.append((len(plist), label))
    body = "\n\n".join(blocks)
    if flows:
        flows.sort(key=lambda x: -x[0])
        body += "\n\n🔁 Перенаправления (кто кого направил):\n" + "\n".join(f for _, f in flows)
    # Список прочитанных вкладок — чтобы было видно, подтянулась ли дневная
    try:
        ti = json.loads(await get_setting("shift_tabs") or "[]")
    except Exception:
        ti = []
    if ti:
        head = "📂 Прочитано вкладок: " + str(len(ti)) + "\n" + "\n".join(
            f"• {nm} — {('⚠️ ошибка' if cnt == -1 else str(cnt) + ' приёмов')}" for nm, cnt in ti)
        head += "\n(Если вашей дневной вкладки тут нет — пришлите её отдельной ссылкой.)\n\n"
        body = head + body
    await _send_block(message, f"📊 *Отчёт по врачам · {period_label}*", body)


@router.message(Command("doctors"))
async def doctors_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    raw = message.text or ""
    parts = raw.split() if raw.startswith("/") else []
    arg = " ".join(parts[1:]).strip()
    try:
        synced, sync_err = await _sync_visits()
        await _ensure_visits_table()
    except Exception as e:
        await message.answer(f"⚠️ Ошибка загрузки данных: {e}\n\nПроверь /visits и /setshift")
        return

    on_date = None
    days = None
    period = None
    if arg:
        if arg.isdigit():
            days = int(arg)
        elif _label_to_period(arg):
            period = _label_to_period(arg)
        else:
            on_date = _norm_date(arg)

    # ── По умолчанию (кнопка «Доктора») — только сводка по месяцам ──
    if not arg:
        aliases = await _get_aliases()
        pct_map = await _get_doctor_percents()

        allv = await db_all("""
            SELECT period, day, doctor, revenue FROM visits WHERE src='shift'
            UNION ALL
            SELECT period, day, doctor, revenue FROM visits v2 WHERE src='clean'
              AND period NOT IN (SELECT DISTINCT period FROM visits WHERE src='shift' AND period IS NOT NULL)
        """)
        if not allv:
            msg = "📊 По врачам пока нет данных.\n\n"
            if sync_err:
                msg += f"⚠️ Таблица: {sync_err}\n\n"
            msg += "Проверь:\n• /visits — что подключено\n• /setshift — таблицы смен\n• /diag — диагностика"
            await message.answer(msg)
            return

        per_map = {}
        for r in allv:
            p = r["period"] or ((r["day"] or "")[:7]) or "—"
            d = _canon_with(r["doctor"] or "—", aliases)
            x = per_map.setdefault(p, {}).setdefault(d, {"n": 0, "rev": 0.0})
            x["n"] += 1
            x["rev"] += r["revenue"] or 0

        ordered = sorted(per_map.keys(), reverse=True)
        out = []
        for p in ordered[:6]:
            docs = per_map[p]
            totn = sum(v["n"] for v in docs.values())
            totr = sum(v["rev"] for v in docs.values())
            lines = [f"📅 *{_period_label(p)}* — {totn} приёмов, {_money(totr)}"]
            for d, v in sorted(docs.items(), key=lambda kv: -kv[1]["rev"]):
                pct = pct_map.get(d)
                zp = f" (ЗП {_money(v['rev'] * pct / 100)})" if pct else ""
                lines.append(f"  • {d}: {v['n']} приёмов, {_money(v['rev'])}{zp}")
            out.append("\n".join(lines))

        tail = "\n\n👇 Выбери месяц для полного отчёта (день + ночь)"
        await _send_block(message, "📊 *Врачи по месяцам*", "\n\n".join(out) + tail)
        ps = await _doctor_periods()
        if ps:
            await message.answer("📅 Выбери месяц:", reply_markup=_doctor_year_kb(ps))
        return

    # ── Подробный отчёт: за конкретный месяц / дату / N дней ──
    DFILTER = "AND doctor IS NOT NULL AND doctor != '' AND doctor != '—' AND LOWER(doctor) NOT LIKE '%не указан%'"
    try:
        if period:
            # shift — основной. clean — только если shift для этого периода нет. zp — только резерв.
            rows = await db_all(f"SELECT doctor,service,kind,ref_from,revenue,percent,pay,src,patient FROM visits WHERE period = ? AND src='shift' {DFILTER}", (period,))
            if not rows:
                rows = await db_all(f"SELECT doctor,service,kind,ref_from,revenue,percent,pay,src,patient FROM visits WHERE period = ? AND src='clean' {DFILTER}", (period,))
            if not rows:
                rows = await db_all(f"SELECT doctor,service,kind,ref_from,revenue,percent,pay,src,patient FROM visits WHERE period = ? AND src='zp' {DFILTER}", (period,))
            if rows:
                zp_pct = {(r["doctor"] or "").lower(): r["percent"] for r in await db_all("SELECT doctor, percent FROM visits WHERE period=? AND src='zp' AND percent>0", (period,))}
                rows = [{**dict(r), "percent": r["percent"] or zp_pct.get((r["doctor"] or "").lower(), 0)} for r in rows]
            period_label = _period_label(period)
        elif on_date:
            rows = await db_all(f"SELECT doctor,service,kind,ref_from,revenue,percent,pay,src,patient FROM visits WHERE day = ? AND src='shift' {DFILTER}", (on_date,))
            if not rows:
                rows = await db_all(f"SELECT doctor,service,kind,ref_from,revenue,percent,pay,src,patient FROM visits WHERE day = ? {DFILTER}", (on_date,))
            period_label = on_date
        else:
            rows = await db_all(f"SELECT doctor,service,kind,ref_from,revenue,percent,pay,src,patient FROM visits WHERE day >= date('now', ?) AND day <= date('now') AND src='shift' {DFILTER}", (f"-{days - 1} day",))
            if not rows:
                rows = await db_all(f"SELECT doctor,service,kind,ref_from,revenue,percent,pay,src,patient FROM visits WHERE day >= date('now', ?) AND day <= date('now') {DFILTER}", (f"-{days - 1} day",))
            period_label = f"{days} дн."
        if not rows:
            await message.answer(f"📊 За {period_label or 'этот период'} данных нет.\n\nПроверь:\n• таблица смен подключена: /setshift")
            return
        await _render_doctor_detail(message, rows, period_label)
    except Exception as e:
        await message.answer(f"⚠️ Ошибка при формировании отчёта: {e}")


@router.message(Command("calllist"))
async def calllist_cmd(message: Message, state: FSMContext):
    """
    /calllist — запустить обзвон по списку.
    После команды отправь список в любом формате:

      +79991234567 Иванова Мария — болит зуб
      89991234568, Петров Иван, подтвердить запись
      Кузнецова Анна +7 999 111-22-33

    Алина позвонит каждому. Результаты придут сюда.
    """
    if message.from_user.id != ADMIN_ID:
        return
    await state.set_state(State_.calllist)
    await message.answer(
        "📋 *Обзвон — Алина позвонит по списку*\n\n"
        "Пришли список в любом формате, каждый человек с новой строки:\n\n"
        "`+79991234567 Иванова Мария — болит зуб`\n"
        "`89991234568 Петров Иван — подтвердить запись`\n"
        "`Кузнецова Анна +7 999 111-22-33`\n\n"
        "Тип звонка определяется автоматически по заметке:\n"
        "• *подтвердить / запись* → звонок-подтверждение\n"
        "• *отзыв / как прошло* → звонок за отзывом\n"
        "• *ничего* → продажный сценарий\n\n"
        "/cancel — отменить",
        parse_mode="Markdown"
    )


@router.message(State_.calllist, Command("cancel"))
async def calllist_cancel(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.clear()
    await message.answer("❌ Отменено.", reply_markup=main_kb())


@router.message(State_.calllist)
async def calllist_receive(message: Message, state: FSMContext):
    """Получаем список, показываем превью, кнопки Запустить / Отмена."""
    if message.from_user.id != ADMIN_ID:
        return

    from call_queue import parse_call_list
    text = message.text or ""
    tasks = parse_call_list(text)

    if not tasks:
        await message.answer(
            "⚠️ Не нашёл ни одного номера. Убедись что в каждой строке есть телефон:\n"
            "`+79991234567 Имя Фамилия`",
            parse_mode="Markdown"
        )
        return

    # Сохраняем список в FSM
    raw_tasks = [{"phone": t.phone, "name": t.name, "note": t.note, "call_type": t.call_type}
                 for t in tasks]
    await state.update_data(tasks=raw_tasks)

    # Превью
    lines = [f"📋 *Список для обзвона — {len(tasks)} чел.*\n"]
    type_emoji = {"confirm": "✅", "review": "⭐", "return": "🔄", "inbound": "📞"}
    for i, t in enumerate(tasks[:20], 1):
        em = type_emoji.get(t.call_type, "📞")
        lines.append(f"{i}. {em} {t.name} — {t.phone}" + (f"\n    _{t.note}_" if t.note else ""))
    if len(tasks) > 20:
        lines.append(f"...и ещё {len(tasks) - 20}")

    lines.append("\n_Алина позвонит по очереди с паузой 45 сек._")

    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="🚀 Запустить", callback_data="callqueue_start"),
        InlineKeyboardButton(text="❌ Отмена",    callback_data="callqueue_cancel"),
    )
    await message.answer("\n".join(lines), parse_mode="Markdown", reply_markup=kb.as_markup())


@router.callback_query(F.data == "callqueue_start")
async def callqueue_start(cq: CallbackQuery, state: FSMContext):
    if cq.from_user.id != ADMIN_ID:
        return
    data = await state.get_data()
    raw_tasks = data.get("tasks", [])
    await state.clear()

    if not raw_tasks:
        await cq.answer("Список пуст")
        return

    from call_queue import CallTask, load_queue, start_queue, _notify
    tasks = [CallTask(**t) for t in raw_tasks]
    load_queue(tasks)

    await cq.message.edit_reply_markup(reply_markup=None)
    await cq.message.answer(
        f"🚀 Запускаю обзвон — {len(tasks)} человек.\n"
        f"Результаты буду присылать по мере звонков.",
    )
    await cq.answer()

    # Запускаем в фоне чтобы не блокировать бот
    asyncio.create_task(start_queue())


@router.callback_query(F.data == "callqueue_cancel")
async def callqueue_cancel_cb(cq: CallbackQuery, state: FSMContext):
    if cq.from_user.id != ADMIN_ID:
        return
    await state.clear()
    await cq.message.edit_reply_markup(reply_markup=None)
    await cq.message.answer("❌ Обзвон отменён.")
    await cq.answer()


# ── Нумерология: обработчик ввода имени + даты ───────────────────────────────

@router.message(State_.numerology)
async def numerology_receive(message: Message, state: FSMContext):
    import re
    from numerology import full_profile, format_profile

    text = (message.text or "").strip()

    # Ищем дату в формате ДД.ММ.ГГГГ или ДД/ММ/ГГГГ или ГГГГ-ММ-ДД
    date_pattern = re.search(r'(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{4}|\d{4}[.\-]\d{2}[.\-]\d{2})', text)
    if not date_pattern:
        await message.answer(
            "Не нашёл дату рождения. Напиши имя и дату вместе:\n\n"
            "`Иванова Мария Сергеевна 15.03.1992`",
            parse_mode="Markdown"
        )
        return

    birth_date = date_pattern.group(0)
    full_name = re.sub(r'(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{4}|\d{4}[.\-]\d{2}[.\-]\d{2})', '', text).strip()
    full_name = ' '.join(full_name.split())

    if len(full_name) < 3:
        await message.answer("Не нашёл имя. Напиши полное имя перед датой:\n\n`Мария Иванова 15.03.1992`", parse_mode="Markdown")
        return

    data = await state.get_data()
    cost = data.get("cost", 25)

    ok = await use_credits(message.from_user.id, "coach", cost)
    if not ok:
        await message.answer("❌ Недостаточно токенов.", reply_markup=profile_kb())
        await state.clear(); return

    thinking = await message.answer("💭", reply_markup=ReplyKeyboardRemove())

    try:
        profile = full_profile(full_name, birth_date)
        profile_text = format_profile(profile)

        system = (
            "Ты — Аура, коуч-наставник по предназначению. "
            "Тебе дан нумерологический профиль человека — используй его как зеркало для глубокого разговора о призвании. "
            "Нумерология — инструмент рефлексии, не судьба. "
            "Сделай анализ живым, конкретным и вдохновляющим. Пиши без лишних звёздочек и хэдеров — просто тёплый живой текст. "
            "Закончи одним сильным вопросом который поможет человеку двигаться к своему пути."
        )

        prompt = (
            f"Профиль:\n{profile_text}\n\n"
            "На основе этого профиля:\n"
            "1. Скажи какой карьерный архетип у этого человека и почему это важно\n"
            "2. Назови 2-3 конкретные сферы или профессии где он может расцвести\n"
            "3. Укажи главную сильную сторону и главный вызов\n"
            "4. Что личный год говорит про сейчас\n"
            "Завершь одним глубоким коучинговым вопросом."
        )

        # Сохраняем профиль чтобы все агенты знали имя и дату рождения
        await save_user_profile(message.from_user.id, full_name, birth_date, profile_text)

        result = await call_text_ai(prompt, system, "claude", uid=message.from_user.id, tool="coach")
        bal = await get_balance(message.from_user.id)

        header = (
            f"🔢 Жизненный путь: {profile['life_path']} — {profile['career_title']}\n"
            f"Число судьбы: {profile['destiny']} · Душа: {profile['soul']} · Личный год: {profile['personal_year']}\n\n"
        )
        full_msg = header + result
        try:
            await thinking.edit_text(full_msg)
        except Exception:
            await message.answer(full_msg)

        await state.set_state(State_.waiting_text)
        await state.update_data(tool="coach", model="claude", cost=cost,
                                 numerology_context=profile_text)
        import random
        continuations = ["Я здесь 💛", "Слушаю тебя.", "Продолжай — я рядом.", "Говори — я слушаю."]
        await message.answer(random.choice(continuations), reply_markup=psy_kb())

    except Exception as e:
        logging.error(f"Numerology error: {e}")
        try:
            await thinking.edit_text("Что-то пошло не так. Попробуй ещё раз.")
        except Exception:
            await message.answer("Что-то пошло не так. Попробуй ещё раз.")
        await state.clear()


@router.message(Command("psych"))
async def psych_cmd(message: Message):
    """
    /psych — начать сессию с AI-психологом Sage.
    /psych reset — сбросить разговор.
    """
    from psych_agent import get_session, reset_session

    uid = str(message.from_user.id)
    parts = (message.text or "").split(maxsplit=1)
    user_input = parts[1].strip() if len(parts) > 1 else ""

    if user_input.lower() in ("reset", "сброс", "новый", "начать заново"):
        reset_session(uid)
        await message.answer("Сессия сброшена. Начнём заново — напиши /psych")
        return

    session = get_session(uid)

    if not user_input:
        # Первое обращение — приветствие
        if not session.history:
            await message.answer(session.greeting())
        else:
            await message.answer("Продолжаем. О чём хочешь поговорить?")
        return

    await message.bot.send_chat_action(message.chat.id, "typing")
    reply = await session.reply(user_input)
    await message.answer(reply)


@router.message(Command("alina"))
async def alina_cmd(message: Message):
    """
    /alina [текст] — тест голосового агента.
    Без текста — начинает новый разговор.
    С текстом — продолжает разговор (как пациент).

    Примеры:
      /alina                      ← приветствие Алины
      /alina Хочу записаться      ← ответ на фразу
      /alina reset                ← сбросить разговор
    """
    if message.from_user.id != ADMIN_ID:
        return
    parts = (message.text or "").split(maxsplit=1)
    user_text = parts[1].strip() if len(parts) > 1 else ""

    call_id = f"tg_{message.from_user.id}"
    base = os.getenv("BASE_URL", "http://localhost:8000")

    try:
        async with __import__("httpx").AsyncClient(timeout=30) as client:
            if user_text.lower() in ("reset", "сброс", "новый"):
                # Сбрасываем разговор
                await client.post(f"{base}/admin/call/end", json={"call_id": call_id})
                await message.answer("🔄 Разговор сброшен. Напиши /alina чтобы начать заново.")
                return

            r = await client.post(
                f"{base}/admin/call/test",
                json={
                    "call_id":      call_id,
                    "message":      user_text or "",
                    "call_type":    "inbound",
                    "patient_name": "",
                }
            )
            data = r.json()

        reply   = data.get("alina", "")
        booked  = data.get("booked", False)
        end     = data.get("end_call", False)

        prefix = "🦷 *Алина:*\n"
        suffix = ""
        if booked:
            b = data.get("booking") or {}
            suffix = (f"\n\n✅ *Записала пациента*\n"
                      f"👤 {b.get('name','?')} | 📞 {b.get('phone','?')}\n"
                      f"🕐 {b.get('time_pref','?')} | 🔖 {b.get('issue','?')}")
        if end:
            suffix += "\n\n_(разговор завершён — /alina reset для нового)_"

        await message.answer(f"{prefix}{reply}{suffix}", parse_mode="Markdown")

    except Exception as e:
        await message.answer(f"⚠️ Агент недоступен: {e}\n\nАгент работает только если запущен FastAPI сервер.")


@router.message(Command("fix"))
async def fix_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("🛠 Опиши проблему после команды. Например:\n"
                             "/fix в отчёте по врачам не считаются первичные\n"
                             "/fix кнопка «Обновить из таблицы» не работает")
        return
    problem = parts[1].strip()
    status = await message.answer("🛠 Инженер разбирается...")
    sys = (AGENT_DEFS["engineer"]["prompt"] +
        "\n\nПользователь описал проблему в его Telegram-боте (Python, aiogram 3). "
        "Дай коротко: 1) диагноз — в чём, вероятно, причина; 2) решение — что и где исправить, "
        "с готовым блоком кода; 3) как применить. По-русски, по делу, без воды.")
    reply = await _agent_call(problem, sys, timeout_s=60)
    try:
        await status.delete()
    except Exception:
        pass
    if not reply:
        await message.answer("Не получилось. Попробуй ещё раз или опиши подробнее.")
        return
    await _send_block(message, "🛠 *Инженер — диагноз и исправление:*", reply)
    await message.answer("ℹ️ Чтобы применить правку к самому боту — нужно обновить файл бота и перезапустить. "
                         "Бот не меняет свой код сам — это защита от поломки.")


@router.message(Command("delshift"))
async def delshift_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    sheets = await _get_shift_sheets()
    parts = (message.text or "").split()
    idx = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    if not (1 <= idx <= len(sheets)):
        lst = "\n".join(f"{i}. …{s[-30:]}" for i, s in enumerate(sheets, 1)) or "пусто"
        await message.answer(f"Укажи номер: /delshift N\n\nТаблицы смен:\n{lst}"); return
    sheets.pop(idx - 1)
    await set_setting("shift_sheets", json.dumps(sheets))
    n, err = await _sync_visits()
    await message.answer(f"🗑 Таблица смены №{idx} удалена. Осталось: {len(sheets)}. Приёмов в базе: {n}.")

@router.message(Command("delvisits"))
async def delvisits_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    sheets = await _get_visit_sheets()
    parts = (message.text or "").split()
    idx = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    if not (1 <= idx <= len(sheets)):
        lst = "\n".join(f"{i}. …{s[-30:]}" for i, s in enumerate(sheets, 1)) or "пусто"
        await message.answer(f"Укажи номер: /delvisits N\n\nВкладки «Приёмы»:\n{lst}"); return
    sheets.pop(idx - 1)
    await set_setting("visit_sheets", json.dumps(sheets))
    n, err = await _sync_visits()
    await message.answer(f"🗑 Вкладка «Приёмы» №{idx} удалена. Осталось: {len(sheets)}. Приёмов в базе: {n}.")

@router.message(Command("delsheet"))
async def delsheet_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    sheets = await _get_sheets()
    parts = (message.text or "").split()
    idx = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    if not (1 <= idx <= len(sheets)):
        lst = "\n".join(f"{i}. …{s[-30:]}" for i, s in enumerate(sheets, 1)) or "пусто"
        await message.answer(f"Укажи номер: /delsheet N\n\nТаблицы /biz:\n{lst}"); return
    sheets.pop(idx - 1)
    await set_setting("biz_sheets", json.dumps(sheets))
    await set_setting("biz_sheet_csv", "")
    n, err = await _biz_sync_from_sheet()
    await message.answer(f"🗑 Таблица №{idx} удалена. Осталось: {len(sheets)}. Строк в базе: {n}.")


# ── /server — управление VPS с Алиной ────────────────────────────────────────

_VPS_INTENTS = {
    # ключ → команда на VPS API
    "логи":        "logs",
    "лог":         "logs",
    "статус":      "status",
    "работает":    "status",
    "перезапусти алину": "restart",
    "рестарт алины":     "restart",
    "перезапусти asterisk": "restart_asterisk",
    "рестарт asterisk":     "restart_asterisk",
    "ресурсы":     "resources",
    "память":      "resources",
    "диск":        "resources",
    "аптайм":      "uptime",
    "звонки":      "calls",
    "активные звонки": "calls",
}


async def _vps_run(command_key: str, raw: bool = False) -> str:
    import aiohttp
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                f"{VPS_API_URL}/run",
                json={"command": command_key, "raw": raw},
                headers={"x-secret": VPS_API_SECRET},
                timeout=aiohttp.ClientTimeout(total=35),
            ) as r:
                data = await r.json()
                return data.get("output", "нет ответа")
    except Exception as e:
        return f"Ошибка подключения к серверу: {e}"


@router.message(Command("server"))
async def server_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = (message.text or "").split(maxsplit=1)
    arg = parts[1].strip().lower() if len(parts) > 1 else ""

    if not arg:
        await message.answer(
            "🖥 <b>Управление сервером Алины</b>\n\n"
            "/server логи — последние логи\n"
            "/server статус — статус сервисов\n"
            "/server перезапусти алину\n"
            "/server перезапусти asterisk\n"
            "/server ресурсы — RAM/CPU/диск\n"
            "/server звонки — активные звонки\n"
            "/server аптайм\n"
            "/server exec &lt;команда&gt; — произвольная команда",
            parse_mode="HTML",
        )
        return

    await message.answer("⏳ Выполняю...")

    if arg.startswith("exec "):
        raw_cmd = arg[5:].strip()
        output = await _vps_run(raw_cmd, raw=True)
    else:
        # Поиск по интентам
        matched = None
        for keyword, cmd_key in _VPS_INTENTS.items():
            if keyword in arg:
                matched = cmd_key
                break
        if not matched:
            matched = arg  # пробуем как ключ напрямую
        output = await _vps_run(matched)

    # Обрезаем если слишком длинный
    if len(output) > 3800:
        output = output[-3800:]

    await message.answer(f"<pre>{output}</pre>", parse_mode="HTML")


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
    start_autoposter(bot)
    start_biz_sync(bot)

    logging.info(f"🚀 AuraAI Bot v3.44 FIX-отчётность запущен | @{BOT_USERNAME}")
    logging.info("✅ ВЕРСИЯ С ВЫБОРОМ ФОРМАТА 9:16 16:9 — если видишь это, новый код работает")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    asyncio.run(main())
