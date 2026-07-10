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


def _fetch_csv(sheet_id: str) -> list[list[str]]:
    import urllib.request
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read().decode("utf-8")
    except Exception as e:
        raise RuntimeError(f"Не удалось скачать таблицу {sheet_id}: {e}")
    return list(csv.reader(io.StringIO(content)))


def _parse_block_sheet(sheet_id: str, shift: str) -> list[dict]:
    """Парсит блочный формат таблицы (дата → врач → строки пациентов)."""
    rows = _fetch_csv(sheet_id)
    records = []
    current_date: Optional[date] = None
    current_doctor: str = ""

    for row in rows:
        cells = [c.strip() for c in row]
        col0 = cells[0] if cells else ""
        col1 = cells[1] if len(cells) > 1 else ""

        if not col0 and not col1:
            continue

        # Дата (иногда с именем: "03.07.2026 -Мутолиб")
        date_match = _DATE_RE.search(col0)
        if date_match and not _NUM_RE.match(col0):
            current_date = _normalize_date(date_match.group(1))
            continue

        # Врач
        doc_match = _DOCTOR_RE.match(col0)
        if doc_match:
            current_doctor = doc_match.group(1).strip().title()
            continue

        # Пропускаем заголовок, итоги, аренду, пустые, хэши
        if col0 in ("№",) or _SKIP_RE.match(col0):
            continue
        if not _NUM_RE.match(col0):
            continue

        # Строка пациента
        patient_service = col1
        if not patient_service or not current_date or not current_doctor:
            continue

        cost_raw = cells[2] if len(cells) > 2 else ""
        pay_raw  = cells[4] if len(cells) > 4 else ""
        anest    = cells[3] if len(cells) > 3 else ""

        cost = _normalize_cost(cost_raw)
        patient_name, service = _split_patient_service(patient_service)

        records.append({
            "shift":        shift,
            "date":         current_date,
            "doctor":       current_doctor,
            "patient":      patient_name.lower(),
            "patient_raw":  patient_name,
            "service":      service,
            "cost":         cost,
            "pay_type":     _normalize_pay(pay_raw),
            "anesthesia":   anest,
        })

    return records


# ════════════════════════════════════════════════════════════════
#  ЗАГРУЗКА ДАННЫХ
# ════════════════════════════════════════════════════════════════

def load_shift_data(days_back: int = 30) -> list[dict]:
    cutoff = date.today() - timedelta(days=days_back)
    all_records = []
    for sheet_id, shift in [(SHEET_DAY, "день"), (SHEET_NIGHT, "ночь")]:
        try:
            recs = _parse_block_sheet(sheet_id, shift)
            filtered = [r for r in recs if r["date"] and r["date"] >= cutoff]
            all_records.extend(filtered)
            log.info(f"Смена '{shift}': загружено {len(filtered)} записей")
        except Exception as e:
            log.warning(f"Ошибка загрузки смены '{shift}': {e}")
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
        result[doc] = {
            "revenue":         round(s["revenue"]),
            "visits":          visits,
            "paid_visits":     s["paid_visits"],
            "unique_patients": len(s["patients"]),
            "avg_check":       round(s["revenue"] / max(s["paid_visits"], 1)),
            "revenue_per_day": round(s["revenue"] / working_days),
            "working_days":    working_days,
            "top_services":    sorted(s["services"].items(), key=lambda x: -x[1])[:3],
            "pay_types":       dict(s["pay_types"]),
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
    total_rev = sum(d["revenue"] for d in doctors.values())
    lines = [
        f"👨‍⚕️ *Врачи за {period_days} дней*\n",
        f"💰 Выручка клиники: *{total_rev:,} ₽*\n",
    ]
    medals = ["🥇", "🥈", "🥉"]
    for i, (doc, d) in enumerate(sorted(doctors.items(), key=lambda x: -x[1]["revenue"]), 1):
        m = medals[i - 1] if i <= 3 else f"{i}\\."
        share = round(d["revenue"] / total_rev * 100) if total_rev else 0
        lines.append(
            f"{m} *{doc}*\n"
            f"   💵 {d['revenue']:,} ₽ ({share}%) · чек {d['avg_check']:,} ₽/визит\n"
            f"   📅 {d['working_days']} дн · {d['revenue_per_day']:,} ₽/день\n"
            f"   👥 {d['unique_patients']} пациентов · {d['visits']} визитов\n"
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

async def full_report(period_days: int = 30, with_ai: bool = True) -> dict:
    records = load_shift_data(period_days)
    if not records:
        return {"error": (
            f"❌ Нет данных за {period_days} дней.\n\n"
            "Проверь:\n"
            "1. Таблицы открыты на просмотр (Поделиться → Все у кого есть ссылка)\n"
            "2. В таблице есть записи с датами за этот период"
        )}
    doctors   = analyze_doctors(records)
    retention = analyze_patient_retention(records)
    result = {
        "doctor_report":    format_doctor_report(doctors, period_days),
        "retention_report": format_retention_report(retention, period_days),
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
