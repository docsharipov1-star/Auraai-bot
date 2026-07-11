"""
Аналитика стоматологической клиники — Google Sheets (CSV export) + AI анализ.

Формат таблицы (блочный):
  Строка: день_недели
  Строка: дата (dd.mm.yyyy)
  Строка: Врач ИМЯ
  Строка: № | ФИО и вид оказанной услуги | Оплата (сумма) | Анестезия | Вид оплаты
  Строки: 1 | пациент услуга | сумма | ... | вид_оплаты
  (потом итог, аренда — пропускаем)

Настройка:
  Таблицы открыть на просмотр: Поделиться → Все у кого есть ссылка → Просматривать
"""

import os
import re
import csv
import asyncio
import logging
import io
from datetime import datetime, timedelta, date
from typing import Optional
from collections import defaultdict

log = logging.getLogger("clinic_analytics")

# ── Google Sheets ID ─────────────────────────────────────────────
SHEET_DAY    = os.getenv("SHEET_DAY",    "1RMlCNKvcW9YYc_S3nUyAR7Rrl9FiybhP4AFc5gUKim8")
SHEET_NIGHT  = os.getenv("SHEET_NIGHT",  "1IebXYtEpJWi9rpUHGmrQk-sPJkBPN-p_dsCkoz4IFko")
SHEET_SALARY = os.getenv("SHEET_SALARY", "10GAbXPUtOvx0tvMSlL_PzFBuxUaI-kWkoCL7k84k-A8")

_DATE_RE   = re.compile(r'(\d{2}\.\d{2}\.\d{4})')
_DOCTOR_RE = re.compile(r'врач\s+(.+)', re.IGNORECASE)
_NUM_RE    = re.compile(r'^\d+$')
_SKIP_RE   = re.compile(r'^(итог|аренда|[a-f0-9]{20,})', re.IGNORECASE)

# ── Экономика клиники ─────────────────────────────────────────────
# Постоянные расходы в месяц → в день
# Аренда 155463 + Налоги 43000 + Яндекс 100000 + Маркетолог 30000
# + Бухгалтер 35000 + Материалы 50000 + Коммуналка 22000 + Мусор 7500 = 442963
MONTHLY_EXPENSES = float(os.getenv("MONTHLY_EXPENSES", "442963"))
DAILY_EXPENSES   = float(os.getenv("DAILY_EXPENSES",   str(round(MONTHLY_EXPENSES / 30))))
TARGET_PROFIT    = float(os.getenv("TARGET_PROFIT",    "50000"))   # цель чистой прибыли в день
DEFAULT_DOCTOR_PCT = float(os.getenv("DEFAULT_DOCTOR_PCT", "30"))

# Процент каждого врача: DR_PCT_КРИСТИНА=30, DR_PCT_БИБО=20 и т.д.
# Ключ — первое слово имени в верхнем регистре
_DOCTOR_PCTS: dict[str, float] = {
    "КРИСТИНА":  30.0,  # Кристина Алибековна
    "БИБО":      20.0,  # Бибо Балаевич
    "БЕГА":      20.0,  # Бега Балаевич
    "КИСИЕВ":   25.0,  # Кисиев Михаил (имплантация; удаление 30% — усредняем)
    "МИХАИЛ":   20.0,  # Кисиев Михаил (альтернативное написание)
    "ДАВЛАТ":   30.0,  # Давлат Зафарович
    "АЛЕКСАНДРОВ": 20.0,
}

def _doctor_pct(doc_name: str) -> float:
    first = doc_name.upper().split()[0] if doc_name.split() else ""
    # Сначала env-override, потом словарь, потом дефолт
    env_key = "DR_PCT_" + first
    if os.getenv(env_key):
        return float(os.getenv(env_key))
    return _DOCTOR_PCTS.get(first, DEFAULT_DOCTOR_PCT)

PAY_TYPES = {
    "нал": "наличные", "налич": "наличные",
    "терминал": "терминал",
    "перевод": "перевод",
    "сбер": "перевод",
    "альфа": "перевод",
    "карта": "терминал",
    "без": "без оплаты",
}


def _normalize_date(val: str) -> Optional[date]:
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(val.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _normalize_cost(val: str) -> float:
    s = str(val).replace(" ", "").replace("₽", "").replace(",", ".").replace("\xa0", "").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def _normalize_pay(val: str) -> str:
    v = val.lower().strip()
    for key, mapped in PAY_TYPES.items():
        if key in v:
            return mapped
    return v or "не указан"


def _build_doctor_map(names: list[str]) -> dict[str, str]:
    """
    Объединяет варианты одного имени: 'Бибо' → 'Бибо Балаевич'.
    Берёт первое слово как ключ — кто длиннее, тот канонический.
    """
    unique = sorted(set(names), key=len, reverse=True)
    canonical: list[str] = []
    mapping: dict[str, str] = {}
    for name in unique:
        first = name.lower().split()[0] if name.split() else name.lower()
        matched = next((c for c in canonical if c.lower().split()[0] == first), None)
        if matched:
            mapping[name] = matched
        else:
            canonical.append(name)
            mapping[name] = name
    return mapping


def _split_patient_service(text: str) -> tuple[str, str]:
    """'Некрасов.М.К. ИМП' → ('Некрасов.М.К.', 'ИМП')"""
    parts = text.strip().split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    if "." in parts[0]:
        # Находим последнюю часть с точкой — это имя
        last_name_idx = max(i for i, p in enumerate(parts) if "." in p)
        name = " ".join(parts[: last_name_idx + 1])
        service = " ".join(parts[last_name_idx + 1 :])
    else:
        name = parts[0]
        service = " ".join(parts[1:])
    return name, service


async def _fetch_csv_async(sheet_id: str) -> list[list[str]]:
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=aiohttp.ClientTimeout(total=20), allow_redirects=True) as resp:
                content = await resp.text(encoding="utf-8")
    except ImportError:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            content = resp.read().decode("utf-8")
    except Exception as e:
        raise RuntimeError(f"Не удалось скачать таблицу {sheet_id}: {e}")
    return list(csv.reader(io.StringIO(content)))


_NUM_DOT_RE = re.compile(r'^\d+\.?$')  # "1", "2", "5." — номер строки


async def _parse_block_sheet(sheet_id: str, shift: str) -> list[dict]:
    """Парсит блочный формат таблицы (дата → врач → строки пациентов).

    Учитывает разделённую оплату: основная строка (№) + продолжение (пустой №).
    Пример: '1 | Иванов беглион | 2750' + '  | Иванов | 700' → один пациент, 3450 ₽
    """
    rows = await _fetch_csv_async(sheet_id)
    records = []
    current_date: Optional[date] = None
    current_doctor: str = ""
    last_row_num: str = ""

    for row in rows:
        cells = [c.strip() for c in row]
        col0 = cells[0] if cells else ""
        col1 = cells[1] if len(cells) > 1 else ""
        cost_raw = cells[2] if len(cells) > 2 else ""

        # Строка полностью пустая или только суммой (продолжение)
        if not col0 and not col1:
            extra = _normalize_cost(cost_raw)
            if extra and records:
                records[-1]["cost"] += extra
            continue

        # Дата (иногда с именем: "03.07.2026 -Мутолиб")
        date_match = _DATE_RE.search(col0)
        if date_match and not _NUM_DOT_RE.match(col0):
            current_date = _normalize_date(date_match.group(1))
            last_row_num = ""
            continue

        # Врач
        doc_match = _DOCTOR_RE.match(col0)
        if doc_match:
            current_doctor = doc_match.group(1).strip().title()
            last_row_num = ""
            continue

        # Пропускаем заголовок, итоги, аренду, хэши
        if col0 == "№" or _SKIP_RE.match(col0):
            continue

        # Продолжение строки: пустой col0 но есть имя/сумма
        if not col0 and col1:
            extra = _normalize_cost(cost_raw)
            if records and current_doctor:
                records[-1]["cost"] += extra
            continue

        # Номер строки пациента: "1", "2", "5." и т.д.
        if not _NUM_DOT_RE.match(col0):
            continue

        clean_num = col0.rstrip(".")

        # Тот же номер строки повторяется (например "5." дважды) → продолжение
        if clean_num == last_row_num and records and records[-1]["doctor"] == current_doctor:
            extra = _normalize_cost(cost_raw)
            records[-1]["cost"] += extra
            continue

        last_row_num = clean_num

        # Строка пациента
        if not current_date or not current_doctor:
            continue

        pay_raw = cells[4] if len(cells) > 4 else ""
        cost = _normalize_cost(cost_raw)
        patient_name, service = _split_patient_service(col1) if col1 else ("", "")

        # Пропускаем пустые строки-заглушки (нет пациента и нет оплаты)
        if not patient_name and cost == 0:
            continue

        records.append({
            "shift":        shift,
            "date":         current_date,
            "doctor":       current_doctor,
            "patient":      patient_name.lower(),
            "patient_raw":  patient_name,
            "service":      service,
            "cost":         cost,
            "pay_type":     _normalize_pay(pay_raw),
            "anesthesia":   cells[3] if len(cells) > 3 else "",
        })

    return records


# ════════════════════════════════════════════════════════════════
#  ЗАГРУЗКА ДАННЫХ
# ════════════════════════════════════════════════════════════════

async def load_shift_data(
    days_back: int = 30,
    year: int = None,
    month: int = None,
    from_date: date = None,
    to_date: date = None,
) -> list[dict]:
    """
    Загружает записи за период. Приоритет: from_date/to_date > year+month > year > days_back.
    Примеры:
      load_shift_data(7)                         — последние 7 дней
      load_shift_data(year=2026, month=7)        — июль 2026
      load_shift_data(year=2026)                 — весь 2026 год
      load_shift_data(from_date=d1, to_date=d2)  — произвольный диапазон
    """
    today = date.today()
    if from_date and to_date:
        d_from, d_to = from_date, to_date
    elif year and month:
        import calendar
        d_from = date(year, month, 1)
        d_to   = date(year, month, calendar.monthrange(year, month)[1])
    elif year:
        d_from = date(year, 1, 1)
        d_to   = date(year, 12, 31)
    else:
        d_from = today - timedelta(days=days_back)
        d_to   = today

    all_records = []
    for sheet_id, shift in [(SHEET_DAY, "день"), (SHEET_NIGHT, "ночь")]:
        try:
            recs = await _parse_block_sheet(sheet_id, shift)
            filtered = [r for r in recs if r["date"] and d_from <= r["date"] <= d_to]
            all_records.extend(filtered)
            log.info(f"Смена '{shift}': загружено {len(filtered)} записей")
        except Exception as e:
            log.warning(f"Ошибка загрузки смены '{shift}': {e}")

    # Нормализация имён врачей (Бибо = Бибо Балаевич)
    if all_records:
        doc_map = _build_doctor_map([r["doctor"] for r in all_records if r["doctor"]])
        for r in all_records:
            r["doctor"] = doc_map.get(r["doctor"], r["doctor"])

    return all_records


# ════════════════════════════════════════════════════════════════
#  АНАЛИТИКА ВРАЧЕЙ
# ════════════════════════════════════════════════════════════════

def analyze_doctors(records: list[dict]) -> dict:
    stats: dict = defaultdict(lambda: {
        "revenue": 0.0, "visits": 0, "paid_visits": 0,
        "patients": set(), "days": set(),
        "services": defaultdict(int), "pay_types": defaultdict(int),
    })

    for r in records:
        doc = r["doctor"]
        if not doc:
            continue
        s = stats[doc]
        s["revenue"]  += r["cost"]
        s["visits"]   += 1
        if r["cost"] > 0:
            s["paid_visits"] += 1
        s["patients"].add(r["patient"])
        s["days"].add(r["date"])
        if r["service"]:
            s["services"][r["service"]] += 1
        s["pay_types"][r["pay_type"]] += 1

    result = {}
    for doc, s in stats.items():
        visits = s["visits"] or 1
        working_days = len(s["days"]) or 1
        revenue = round(s["revenue"])
        pct = _doctor_pct(doc)
        doctor_earn = round(revenue * pct / 100)
        result[doc] = {
            "revenue":         revenue,
            "visits":          visits,
            "paid_visits":     s["paid_visits"],
            "unique_patients": len(s["patients"]),
            "avg_check":       round(revenue / max(s["paid_visits"], 1)),
            "revenue_per_day": round(revenue / working_days),
            "working_days":    working_days,
            "top_services":    sorted(s["services"].items(), key=lambda x: -x[1])[:3],
            "pay_types":       dict(s["pay_types"]),
            "doctor_pct":      pct,
            "doctor_earn":     doctor_earn,
            "clinic_net":      revenue - doctor_earn,
        }
    return result


# ════════════════════════════════════════════════════════════════
#  ВОЗВРАЩАЕМОСТЬ ПАЦИЕНТОВ
# ════════════════════════════════════════════════════════════════

def analyze_patient_retention(records: list[dict]) -> dict:
    """
    Считает возвращаемость по имени пациента.
    Если пациент встречается в разные даты — вернулся.
    """
    patient_dates: dict = defaultdict(set)
    patient_doctors: dict = defaultdict(set)

    for r in records:
        p = r["patient"]
        if not p or p in ("", "пациент", "пац"):
            continue
        patient_dates[p].add(r["date"])
        patient_doctors[p].add(r["doctor"])

    total = len(patient_dates)
    returned = sum(1 for dates in patient_dates.values() if len(dates) > 1)
    single   = total - returned

    # Пациенты которые были у нескольких врачей (направление)
    cross_doctor = sum(1 for docs in patient_doctors.values() if len(docs) > 1)

    return {
        "total_patients":  total,
        "returned":        returned,
        "returned_pct":    round(returned / total * 100) if total else 0,
        "single_visit":    single,
        "single_pct":      round(single / total * 100) if total else 0,
        "cross_doctor":    cross_doctor,
        "cross_pct":       round(cross_doctor / total * 100) if total else 0,
    }


# ════════════════════════════════════════════════════════════════
#  AI РЕКОМЕНДАЦИИ
# ════════════════════════════════════════════════════════════════

async def generate_recommendations(doctors: dict, retention: dict, period_days: int) -> str:
    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_KEY", ""))
    except ImportError:
        return "Установи anthropic для AI-рекомендаций."

    docs_lines = []
    for doc, d in sorted(doctors.items(), key=lambda x: -x[1]["revenue"])[:10]:
        docs_lines.append(
            f"• {doc}: выручка {d['revenue']:,}₽ за {d['working_days']} дн., "
            f"пациентов {d['unique_patients']}, визитов {d['visits']}, "
            f"ср.чек {d['avg_check']:,}₽, в день {d['revenue_per_day']:,}₽"
        )

    prompt = f"""Ты — аналитик стоматологической клиники. Данные за {period_days} дней.

ВРАЧИ:
{chr(10).join(docs_lines)}

ВОЗВРАЩАЕМОСТЬ ПАЦИЕНТОВ:
- Уникальных пациентов: {retention['total_patients']}
- Вернулись (были в разные дни): {retention['returned']} ({retention['returned_pct']}%)
- Пришли только 1 раз: {retention['single_visit']} ({retention['single_pct']}%)
- Были у нескольких врачей: {retention['cross_doctor']} ({retention['cross_pct']}%)

Дай краткий анализ:
1. Кто из врачей работает эффективнее всего и почему
2. У кого низкий чек или мало пациентов — что делать
3. Возвращаемость {retention['returned_pct']}% — это хорошо или нет, как улучшить
4. 3 конкретных действия на эту неделю

Пиши конкретно, называй врачей по имени. Без лишних слов."""

    msg = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}]
    )
    return msg.content[0].text.strip()


# ════════════════════════════════════════════════════════════════
#  ФОРМАТИРОВАНИЕ ДЛЯ TELEGRAM
# ════════════════════════════════════════════════════════════════

def format_doctor_report(doctors: dict, period_days: int = 30) -> str:
    if not doctors:
        return "❌ Нет данных по врачам."
    total_rev    = sum(d["revenue"] for d in doctors.values())
    total_to_doc = sum(d["doctor_earn"] for d in doctors.values())
    clinic_gross = total_rev - total_to_doc
    daily_exp    = DAILY_EXPENSES * period_days
    clinic_net   = clinic_gross - daily_exp
    avg_doc_pct  = round(total_to_doc / total_rev * 100) if total_rev else 0
    # Нужная выручка для цели: (расходы + цель_прибыли) / (1 - средний_% врачам)
    need_per_day = (DAILY_EXPENSES + TARGET_PROFIT) / max(1 - avg_doc_pct / 100, 0.01)

    lines = [
        f"🏥 *Отчёт клиники за {period_days} дн.*\n",
        f"💰 Выручка: *{total_rev:,} ₽*",
        f"👨‍⚕️ Врачам (~{avg_doc_pct}%): *{total_to_doc:,} ₽*",
        f"🏢 Клинике до расходов: *{clinic_gross:,} ₽*",
        f"📉 Расходы ({DAILY_EXPENSES:,.0f} ₽/день): *{daily_exp:,.0f} ₽*",
        f"{'✅' if clinic_net >= 0 else '❌'} Чистая прибыль: *{clinic_net:,.0f} ₽*",
        f"🎯 Цель {TARGET_PROFIT:,.0f} ₽/день → нужно *{need_per_day:,.0f} ₽/день*\n",
    ]
    medals = ["🥇", "🥈", "🥉"]
    for i, (doc, d) in enumerate(sorted(doctors.items(), key=lambda x: -x[1]["revenue"]), 1):
        m = medals[i - 1] if i <= 3 else f"{i}\\."
        share = round(d["revenue"] / total_rev * 100) if total_rev else 0
        lines.append(
            f"{m} *{doc}*\n"
            f"   💵 {d['revenue']:,} ₽ ({share}%) · чек {d['avg_check']:,} ₽\n"
            f"   💼 Его доля {d['doctor_pct']:.0f}%: {d['doctor_earn']:,} ₽ · клинике: {d['clinic_net']:,} ₽\n"
            f"   👥 {d['unique_patients']} пац · {d['visits']} визит · {d['working_days']} дн\n"
        )
    return "\n".join(lines)


def format_retention_report(retention: dict, period_days: int = 30) -> str:
    def bar(pct: int) -> str:
        filled = min(pct // 5, 20)
        return "█" * filled + "░" * (20 - filled)

    lines = [
        f"🔄 *Возвращаемость пациентов* за {period_days} дней\n",
        f"👥 Уникальных пациентов: *{retention['total_patients']}*\n",
        f"✅ Вернулись на повторный: *{retention['returned']}* — {retention['returned_pct']}%",
        f"   {bar(retention['returned_pct'])}",
        f"❌ Пришли 1 раз: *{retention['single_visit']}* — {retention['single_pct']}%",
        f"   {bar(retention['single_pct'])}",
        f"🔁 Были у нескольких врачей: *{retention['cross_doctor']}* — {retention['cross_pct']}%",
    ]
    return "\n".join(lines)


# ════════════════════════════════════════════════════════════════
#  ГЛАВНЫЙ МЕТОД
# ════════════════════════════════════════════════════════════════

async def full_report(
    period_days: int = 30,
    with_ai: bool = True,
    days_back: int = None,
    year: int = None,
    month: int = None,
    from_date: date = None,
    to_date: date = None,
) -> dict:
    records = await load_shift_data(
        days_back=days_back or period_days,
        year=year, month=month,
        from_date=from_date, to_date=to_date,
    )
    if not records:
        return {"error": (
            f"❌ Нет данных за {period_days} дней.\n\n"
            "Проверь:\n"
            "1. Таблицы открыты на просмотр (Поделиться → Все у кого есть ссылка)\n"
            "2. В таблице есть записи с датами за этот период"
        )}
    doctors   = analyze_doctors(records)
    retention = analyze_patient_retention(records)
    eff_days = days_back or period_days
    result = {
        "doctor_report":    format_doctor_report(doctors, eff_days),
        "retention_report": format_retention_report(retention, eff_days),
        "raw_doctors":      doctors,
        "raw_retention":    retention,
        "total_rows":       len(records),
    }
    if with_ai:
        result["ai_recs"] = await generate_recommendations(doctors, retention, period_days)
    return result


if __name__ == "__main__":
    import sys
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    async def main():
        print(f"Загружаю данные за {days} дней...\n")
        r = await full_report(days, with_ai=False)
        if "error" in r:
            print(r["error"]); return
        print(f"Записей: {r['total_rows']}\n")
        print(r["doctor_report"])
        print("\n" + "=" * 50)
        print(r["retention_report"])
    asyncio.run(main())
