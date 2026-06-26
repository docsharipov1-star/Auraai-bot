"""
╔══════════════════════════════════════════════════════╗
║     Clinic Multi-Agent System for AuraAI Bot         ║
║                                                      ║
║  Агенты:                                             ║
║  1. AnalystAgent  — анализирует код клиники          ║
║  2. TesterAgent   — находит баги и edge cases        ║
║  3. DeveloperAgent — реализует улучшения             ║
║  4. ClinicBotAgent — AI-аналитика прямо в боте       ║
╚══════════════════════════════════════════════════════╝

Использование:
  python clinic_agents.py analyze   # анализ кода
  python clinic_agents.py test      # тест-кейсы
  python clinic_agents.py improve   # предложить улучшения
  python clinic_agents.py chat      # интерактивный режим

Env:
  ANTHROPIC_KEY=sk-ant-...
"""

import asyncio
import json
import os
import sys
import textwrap
from pathlib import Path

import anthropic

# ── Конфиг ──────────────────────────────────────────
MODEL = "claude-opus-4-8"
BOT_FILE = Path(__file__).parent / "auraai_bot_v3.py"
MAX_CODE_CHARS = 80_000  # читаем не весь файл целиком

# ── Инициализация клиента ────────────────────────────
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_KEY") or os.getenv("ANTHROPIC_API_KEY", ""))


# ══════════════════════════════════════════════════════
#  ИНСТРУМЕНТЫ (tools) для агентов
# ══════════════════════════════════════════════════════

def read_bot_section(section: str) -> str:
    """Читает нужную секцию кода бота по ключевому слову."""
    text = BOT_FILE.read_text(encoding="utf-8")
    lines = text.splitlines()
    result = []
    in_section = False
    for line in lines:
        if section.lower() in line.lower():
            in_section = True
        if in_section:
            result.append(line)
        if in_section and len(result) > 300:
            break
    return "\n".join(result[:300]) if result else f"Секция '{section}' не найдена"


def search_code(keyword: str) -> str:
    """Поиск по коду бота."""
    text = BOT_FILE.read_text(encoding="utf-8")
    lines = text.splitlines()
    hits = []
    for i, line in enumerate(lines, 1):
        if keyword.lower() in line.lower():
            start = max(0, i - 3)
            end = min(len(lines), i + 3)
            hits.append(f"\n--- строки {start+1}-{end} ---")
            hits.extend(f"{start+j+1}: {lines[start+j]}" for j in range(end - start))
    return "\n".join(hits[:200]) if hits else f"'{keyword}' не найдено"


def get_db_schema() -> str:
    """Возвращает схему БД из кода."""
    return read_bot_section("CREATE TABLE")


def get_clinic_functions() -> str:
    """Возвращает список функций клинической части."""
    text = BOT_FILE.read_text(encoding="utf-8")
    lines = text.splitlines()
    clinic_funcs = []
    keywords = ["biz", "visit", "shift", "doctor", "salary", "врач", "смен", "finance"]
    for i, line in enumerate(lines, 1):
        if line.strip().startswith(("async def ", "def ")) and any(k in line.lower() for k in keywords):
            clinic_funcs.append(f"{i}: {line.strip()}")
    return "\n".join(clinic_funcs) if clinic_funcs else "Функции не найдены"


def write_report(filename: str, content: str) -> str:
    """Сохраняет отчёт агента в файл."""
    path = Path(__file__).parent / filename
    path.write_text(content, encoding="utf-8")
    return f"✅ Отчёт сохранён: {path}"


TOOLS = [
    {
        "name": "read_bot_section",
        "description": "Читает секцию кода бота по ключевому слову. Используй когда нужно изучить конкретную часть кода.",
        "input_schema": {
            "type": "object",
            "properties": {
                "section": {"type": "string", "description": "Ключевое слово для поиска секции (например: 'biz_finance', 'visits', 'shift')"}
            },
            "required": ["section"]
        }
    },
    {
        "name": "search_code",
        "description": "Поиск по коду бота. Возвращает строки с контекстом.",
        "input_schema": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "Ключевое слово для поиска"}
            },
            "required": ["keyword"]
        }
    },
    {
        "name": "get_db_schema",
        "description": "Возвращает схему базы данных (CREATE TABLE) из кода бота.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "get_clinic_functions",
        "description": "Возвращает список функций, связанных с клиникой (врачи, смены, финансы, пациенты).",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "write_report",
        "description": "Сохраняет отчёт в файл.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "Имя файла (например: analysis_report.md)"},
                "content": {"type": "string", "description": "Содержимое отчёта"}
            },
            "required": ["filename", "content"]
        }
    }
]


def execute_tool(name: str, args: dict) -> str:
    """Выполняет вызов инструмента."""
    if name == "read_bot_section":
        return read_bot_section(args["section"])
    elif name == "search_code":
        return search_code(args["keyword"])
    elif name == "get_db_schema":
        return get_db_schema()
    elif name == "get_clinic_functions":
        return get_clinic_functions()
    elif name == "write_report":
        return write_report(args["filename"], args["content"])
    return f"Инструмент '{name}' не найден"


# ══════════════════════════════════════════════════════
#  БАЗОВЫЙ АГЕНТ
# ══════════════════════════════════════════════════════

def run_agent(system_prompt: str, user_message: str, verbose: bool = True) -> str:
    """Запускает агента с инструментами до финального ответа."""
    messages = [{"role": "user", "content": user_message}]

    if verbose:
        print(f"\n{'='*60}")
        print(f"🤖 Агент запущен...")
        print(f"{'='*60}")

    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=8192,
            thinking={"type": "adaptive"},
            system=system_prompt,
            tools=TOOLS,
            messages=messages
        )

        # Добавляем ответ ассистента
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            # Финальный текстовый ответ
            text = next((b.text for b in response.content if b.type == "text"), "")
            return text

        if response.stop_reason == "tool_use":
            # Обрабатываем вызовы инструментов
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    if verbose:
                        print(f"\n🔧 Вызов инструмента: {block.name}({json.dumps(block.input, ensure_ascii=False)[:80]})")
                    result = execute_tool(block.name, block.input)
                    if verbose:
                        preview = result[:200].replace('\n', ' ')
                        print(f"   ↳ {preview}...")
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result
                    })
            messages.append({"role": "user", "content": tool_results})
        else:
            break

    return ""


# ══════════════════════════════════════════════════════
#  АГЕНТ 1: АНАЛИТИК КОДА
# ══════════════════════════════════════════════════════

ANALYST_SYSTEM = """Ты — старший Python-разработчик, специализирующийся на анализе Telegram-ботов для клиник.

Твоя задача — проанализировать клиническую часть бота AuraAI (врачи, смены, пациенты, финансы).

При анализе:
1. Изучи схему БД (таблицы visits, biz_finance, shift, doctor)
2. Просмотри функции клинической части
3. Найди потенциальные проблемы: баги, edge cases, missing validation
4. Оцени качество парсинга Google Sheets (смены, визиты)
5. Проверь логику расчёта ФОТ врачей и финансовых отчётов

Используй инструменты для изучения кода. Напиши детальный отчёт на русском языке."""


def run_analyst() -> str:
    print("\n🔍 АНАЛИТИК: Изучаю клиническую часть бота...")
    result = run_agent(
        ANALYST_SYSTEM,
        "Проведи полный анализ клинической части бота. Изучи схему БД, функции обработки смен и визитов, "
        "логику финансовых отчётов. Найди проблемы и слабые места. "
        "ОБЯЗАТЕЛЬНО в конце вызови инструмент write_report с filename='analysis_report.md' и всем текстом анализа."
    )
    path = Path(__file__).parent / "analysis_report.md"
    if not path.exists() and result:
        path.write_text(result, encoding="utf-8")
        print(f"💾 Сохранено: {path}")
    print("\n✅ Анализ завершён!")
    return result


# ══════════════════════════════════════════════════════
#  АГЕНТ 2: ТЕСТИРОВЩИК
# ══════════════════════════════════════════════════════

TESTER_SYSTEM = """Ты — QA-инженер для Telegram-бота клиники.

Твоя задача — найти баги и написать тест-кейсы для клинической части AuraAI бота.

Фокус:
1. Парсинг Google Sheets (смены дней/ночей, визиты врачей) — edge cases в форматах дат, имён
2. Расчёт ФОТ врачей — правильность процентов, алиасов
3. Финансовая отчётность — агрегация данных за период
4. Команды /biz, /setshift, /setvisits — корректность обработки
5. Синхронизация из таблиц — что происходит при дублях, пустых строках, неизвестных врачах

Для каждого тест-кейса укажи:
- Описание
- Входные данные
- Ожидаемый результат
- Возможная проблема

Используй инструменты для изучения кода. Сохрани отчёт в test_cases.md"""


def run_tester() -> str:
    print("\n🧪 ТЕСТИРОВЩИК: Ищу баги и пишу тест-кейсы...")
    result = run_agent(
        TESTER_SYSTEM,
        "Изучи функции парсинга смен (_parse_shift_rows, _fetch_shift_rows), обработки визитов, "
        "расчёта ФОТ (_get_doctor_percents) и финансовых отчётов (_biz_agg). "
        "Напиши тест-кейсы и найди потенциальные баги. "
        "ОБЯЗАТЕЛЬНО в конце вызови инструмент write_report с filename='test_cases.md' и всем текстом."
    )
    path = Path(__file__).parent / "test_cases.md"
    if not path.exists() and result:
        path.write_text(result, encoding="utf-8")
        print(f"💾 Сохранено: {path}")
    print("\n✅ Тест-кейсы готовы!")
    return result


# ══════════════════════════════════════════════════════
#  АГЕНТ 3: РАЗРАБОТЧИК УЛУЧШЕНИЙ
# ══════════════════════════════════════════════════════

DEVELOPER_SYSTEM = """Ты — опытный Python-разработчик, который улучшает Telegram-бота для клиники.

Твоя задача — предложить конкретные улучшения для клинической части AuraAI бота и написать код.

Области для улучшений:
1. Новые отчёты (топ врачей по выручке, динамика пациентов, сезонность)
2. Улучшение UX команд (/biz, /doctors) — более информативные сообщения
3. Автоматическое определение врачей из таблицы (без ручного /alias)
4. Уведомления администратору (план vs факт, аномалии)
5. Экспорт данных (CSV, Excel)

Для каждого улучшения напиши:
- Описание фичи
- Готовый Python-код (фрагмент для вставки в бот)
- Как подключить

Используй инструменты для понимания текущей структуры кода."""


def run_developer() -> str:
    print("\n⚙️ РАЗРАБОТЧИК: Создаю улучшения...")
    result = run_agent(
        DEVELOPER_SYSTEM,
        "Изучи текущие команды клиники (biz_start, biz_menu, doctors_cmd) и схему данных. "
        "Предложи и реализуй 3-5 конкретных улучшений с готовым кодом. "
        "ОБЯЗАТЕЛЬНО в конце вызови инструмент write_report с filename='improvements.md' и всем текстом."
    )
    path = Path(__file__).parent / "improvements.md"
    if not path.exists() and result:
        path.write_text(result, encoding="utf-8")
        print(f"💾 Сохранено: {path}")
    print("\n✅ Улучшения готовы!")
    return result


# ══════════════════════════════════════════════════════
#  АГЕНТ 4: AI-АНАЛИТИК КЛИНИКИ (для интеграции в бота)
# ══════════════════════════════════════════════════════

CLINIC_ANALYST_SYSTEM = """Ты — AI-аналитик для медицинской клиники. Анализируешь данные и даёшь умные советы.

Данные клиники предоставлены в формате JSON. Твои задачи:
1. Дать краткое резюме периода (ключевые цифры)
2. Выявить тренды и аномалии
3. Дать 2-3 конкретных рекомендации
4. Ответить на конкретный вопрос пользователя

Пиши чётко, по-деловому, на русском. Используй эмодзи для читаемости.
Будь конкретным: цифры, проценты, сравнения."""


def analyze_clinic_data(data: dict, question: str = "") -> str:
    """
    Анализирует данные клиники через AI.
    Можно интегрировать в бот как команду /ai_report.

    data: словарь с данными (revenue, expenses, patients, doctors, etc.)
    question: конкретный вопрос пользователя (опционально)
    """
    data_json = json.dumps(data, ensure_ascii=False, indent=2)
    user_msg = f"Данные клиники:\n{data_json}"
    if question:
        user_msg += f"\n\nВопрос: {question}"
    else:
        user_msg += "\n\nПроведи анализ и дай рекомендации."

    response = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        thinking={"type": "adaptive"},
        system=CLINIC_ANALYST_SYSTEM,
        messages=[{"role": "user", "content": user_msg}]
    )
    return next((b.text for b in response.content if b.type == "text"), "")


# ══════════════════════════════════════════════════════
#  ИНТЕРАКТИВНЫЙ РЕЖИМ
# ══════════════════════════════════════════════════════

INTERACTIVE_SYSTEM = """Ты — эксперт по Telegram-боту AuraAI для клиники.
Помогаешь разрабатывать, тестировать и улучшать его клиническую часть.
Используй инструменты для изучения кода когда это нужно.
Отвечай на русском, конкретно и по делу."""


def interactive_mode():
    print("\n🤖 Интерактивный режим мультиагента клиники")
    print("   Задавай любые вопросы о боте. 'exit' для выхода.\n")

    messages = []
    while True:
        try:
            user_input = input("Ты: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nВыход.")
            break

        if user_input.lower() in ("exit", "quit", "выход"):
            break
        if not user_input:
            continue

        messages.append({"role": "user", "content": user_input})

        # Агентный цикл с историей
        while True:
            response = client.messages.create(
                model=MODEL,
                max_tokens=4096,
                thinking={"type": "adaptive"},
                system=INTERACTIVE_SYSTEM,
                tools=TOOLS,
                messages=messages
            )

            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "end_turn":
                text = next((b.text for b in response.content if b.type == "text"), "")
                print(f"\n🤖 Агент: {text}\n")
                break

            if response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        print(f"   [🔧 {block.name}]")
                        result = execute_tool(block.name, block.input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result
                        })
                messages.append({"role": "user", "content": tool_results})
            else:
                break


# ══════════════════════════════════════════════════════
#  ПРИМЕР ИНТЕГРАЦИИ В БОТ (aiogram handler)
# ══════════════════════════════════════════════════════

AIOGRAM_HANDLER_EXAMPLE = '''
# Добавь в auraai_bot_v3.py:

@router.message(Command("ai_report"))
async def ai_report_cmd(message: Message):
    """AI-анализ финансов клиники за последние 30 дней."""
    if message.from_user.id != ADMIN_ID:
        return

    await message.answer("🤖 Анализирую данные... подождите")

    # Собираем данные за последние 30 дней
    from clinic_agents import analyze_clinic_data

    data = await _biz_agg(30)  # агрегация за 30 дней

    # Добавляем топ врачей
    doctors = await db_all(
        "SELECT doctor, SUM(revenue) as rev, COUNT(*) as visits "
        "FROM visits WHERE src=\\'shift\\' AND day >= date(\\'now\\', \\'-30 day\\') "
        "GROUP BY doctor ORDER BY rev DESC LIMIT 10"
    )
    data["top_doctors"] = [dict(r) for r in doctors] if doctors else []

    question = (message.text or "").replace("/ai_report", "").strip()
    report = analyze_clinic_data(data, question or "")

    await message.answer(f"📊 *AI-анализ клиники (30 дней)*\\n\\n{report}", parse_mode="Markdown")
'''


# ══════════════════════════════════════════════════════
#  ГЛАВНЫЙ БЛОК
# ══════════════════════════════════════════════════════

def print_help():
    print("""
🏥 Мультиагентная система для клиники AuraAI

Использование:
  python clinic_agents.py analyze    — анализ кода (AnalystAgent)
  python clinic_agents.py test       — тест-кейсы (TesterAgent)
  python clinic_agents.py improve    — улучшения с кодом (DeveloperAgent)
  python clinic_agents.py all        — запустить всех агентов
  python clinic_agents.py chat       — интерактивный режим
  python clinic_agents.py demo       — демо AI-анализа данных

Результаты сохраняются в:
  analysis_report.md
  test_cases.md
  improvements.md
""")


def demo_clinic_analysis():
    """Демонстрация AI-анализа данных клиники."""
    print("\n🏥 Демо: AI-анализ данных клиники\n")

    sample_data = {
        "label": "30 дней",
        "patients": 287,
        "revenue": 1_850_000,
        "expenses": 620_000,
        "profit": 1_230_000,
        "check": 6_446,
        "categories": {
            "ФОТ врачей": 370_000,
            "Аренда": 150_000,
            "Материалы": 100_000,
        },
        "prev_revenue": 1_620_000,
        "prev_profit": 980_000,
        "top_doctors": [
            {"doctor": "Иванова А.С.", "rev": 420_000, "visits": 52},
            {"doctor": "Петров Д.К.", "rev": 380_000, "visits": 48},
            {"doctor": "Сидорова М.В.", "rev": 290_000, "visits": 38},
        ]
    }

    print("Данные:", json.dumps(sample_data, ensure_ascii=False, indent=2))
    print("\n" + "="*60)
    print("AI-анализ:")
    print("="*60)

    result = analyze_clinic_data(sample_data, "Кто из врачей показал лучший результат и почему?")
    print(result)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"

    if not client.api_key:
        print("❌ Установи ANTHROPIC_KEY в .env или окружении")
        sys.exit(1)

    if cmd == "analyze":
        run_analyst()
    elif cmd == "test":
        run_tester()
    elif cmd == "improve":
        run_developer()
    elif cmd == "all":
        print("🚀 Запускаем всех агентов...")
        run_analyst()
        run_tester()
        run_developer()
        print("\n✅ Все агенты завершили работу!")
        print("📄 Отчёты: analysis_report.md, test_cases.md, improvements.md")
    elif cmd == "chat":
        interactive_mode()
    elif cmd == "demo":
        demo_clinic_analysis()
    elif cmd == "handler":
        print("📋 Пример обработчика для бота:\n")
        print(AIOGRAM_HANDLER_EXAMPLE)
    else:
        print_help()
