"""
Аналитика стоматологической клиники — Google Sheets (CSV export) + AI анализ.

Что умеет:
- Читает 3 таблицы через публичный CSV-экспорт (без API-ключей)
- Считает эффективность каждого врача
- Отслеживает первичных пациентов (пришёл → остался → перенаправлен)
- Генерирует AI-рекомендации через Claude
- Отправляет отчёты в Telegram

Настройка:
  1. Таблицы открыть на просмотр: Поделиться → Все у кого есть ссылка → Просматривать
  2. Прописать SHEET_DAY, SHEET_NIGHT, SHEET_SALARY в Railway ENV (или оставить дефолт)
"""

import os
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

# ── Маппинг колонок (настрой под свои таблицы) ──────────────────
COL_MAP = {
    "date":     os.getenv("COL_DATE",     "Дата"),
    "doctor":   os.getenv("COL_DOCTOR",   "Врач"),
    "patient":  os.getenv("COL_PATIENT",  "ФИО пациента"),
    "service":  os.getenv("COL_SERVICE",  "Услуга"),
    "cost":     os.getenv("COL_COST",     "Стоимость"),
    "paid":     os.getenv("COL_PAID",     "Оплачено"),
    "status":   os.getenv("COL_STATUS",   "Статус"),
    "referred": os.getenv("COL_REFERRED", "Перенаправлен"),
    "source":   os.getenv("COL_SOURCE",   "Источник"),
}

PRIMARY_VALUES = {"первичный", "первич", "новый", "new", "1", "primary", "перв"}


def _csv_url(sheet_id: str, gid: int = 0) -> str:
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"


def _fetch_sheet_csv(sheet_id: str) -> list[dict]:
    """Скачивает лист как CSV и возвращает список словарей."""
    import urllib.request
    url = _csv_url(sheet_id)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read().decode("utf-8")
    except Exception as e:
        raise RuntimeError(f"Не удалось скачать таблицу {sheet_id}: {e}")

    reader = csv.DictReader(io.StringIO(content))
    rows = []
    for row in reader:
        # убираем BOM и лишние пробелы в ключах
        clean = {k.lstrip("﻿").strip(): v for k, v in row.items()}
        rows.append(clean)
    return rows


def _normalize_cost(val) -> float:
    if not val:
        return 0.0
    s = str(val).replace(" ", "").replace("₽", "").replace(",", ".").replace("\xa0", "").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def _normalize_date(val) -> Optional[date]:
    if not val:
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%d.%m.%y", "%d-%m-%Y"):
        try:
            return datetime.strptime(str(val).strip(), fmt).date()
        except ValueError:
            continue
    return None


def _get_col(row: dict, field: str) -> str:
    col_name = COL_MAP.get(field, field)
    if col_name in row:
        return str(row[col_name]).strip()
    for key in row:
        if key.lower() == col_name.lower():
            return str(row[key]).strip()
    return ""


# ════════════════════════════════════════════════════════════════
#  ЗАГРУЗКА ДАННЫХ
# ════════════════════════════════════════════════════════════════

def load_shift_data(days_back: int = 30) -> list[dict]:
    """Объединяет дневную и ночную смены за N дней."""
    cutoff = date.today() - timedelta(days=days_back)
    rows = []
    for sheet_id, shift in [(SHEET_DAY, "день"), (SHEET_NIGHT, "ночь")]:
        try:
            raw = _fetch_sheet_csv(sheet_id)
            for r in raw:
                d = _normalize_date(_get_col(r, "date"))
                if d and d >= cutoff:
                    rows.append({
                        "shift":    shift,
                        "date":     d,
                        "doctor":   _get_col(r, "doctor"),
                        "patient":  _get_col(r, "patient"),
                        "service":  _get_col(r, "service"),
                        "cost":     _normalize_cost(_get_col(r, "cost")),
                        "paid":     _normalize_cost(_get_col(r, "paid")),
                        "status":   _get_col(r, "status").lower(),
                        "referred": _get_col(r, "referred"),
                        "source":   _get_col(r, "source"),
                    })
        except Exception as e:
            log.warning(f"Ошибка загрузки смены '{shift}': {e}")
    return rows


def load_salary_data() -> list[dict]:
    try:
        return _fetch_sheet_csv(SHEET_SALARY)
    except Exception as e:
        log.warning(f"Ошибка загрузки зарплат: {e}")
        return []


# ════════════════════════════════════════════════════════════════
#  АНАЛИТИКА ВРАЧЕЙ
# ════════════════════════════════════════════════════════════════

def analyze_doctors(rows: list[dict]) -> dict:
    stats = defaultdict(lambda: {
        "revenue": 0.0, "paid": 0.0, "visits": 0,
        "primary": 0, "referred_out": 0, "referred_in": 0,
        "patients": set(), "services": defaultdict(int), "days": set(),
    })

    for r in rows:
        doc = r["doctor"]
        if not doc:
            continue
        s = stats[doc]
        s["revenue"] += r["cost"]
        s["paid"]    += r["paid"] if r["paid"] else r["cost"]
        s["visits"]  += 1
        s["patients"].add(r["patient"])
        s["days"].add(r["date"])
        if r["service"]:
            s["services"][r["service"]] += 1
        if r["status"] in PRIMARY_VALUES:
            s["primary"] += 1
        if r["referred"]:
            s["referred_out"] += 1
            ref_doc = r["referred"].strip()
            if ref_doc in stats:
                stats[ref_doc]["referred_in"] += 1

    result = {}
    for doc, s in stats.items():
        visits = s["visits"] or 1
        working_days = len(s["days"]) or 1
        result[doc] = {
            "revenue":          round(s["revenue"]),
            "paid":             round(s["paid"]),
            "visits":           visits,
            "unique_patients":  len(s["patients"]),
            "avg_check":        round(s["revenue"] / visits),
            "revenue_per_day":  round(s["revenue"] / working_days),
            "primary":          s["primary"],
            "primary_pct":      round(s["primary"] / visits * 100),
            "referred_out":     s["referred_out"],
            "referred_in":      s["referred_in"],
            "retention_pct":    round((visits - s["primary"]) / visits * 100) if visits else 0,
            "top_services":     sorted(s["services"].items(), key=lambda x: -x[1])[:3],
            "working_days":     working_days,
        }
    return result


# ════════════════════════════════════════════════════════════════
#  ВОРОНКА ПЕРВИЧНЫХ ПАЦИЕНТОВ
# ════════════════════════════════════════════════════════════════

def analyze_patient_flow(rows: list[dict]) -> dict:
    patient_visits = defaultdict(list)
    for r in rows:
        if r["patient"]:
            patient_visits[r["patient"]].append(r)

    total_primary = stayed = referred = single_visit = 0
    sources = defaultdict(int)

    for patient, visits in patient_visits.items():
        is_primary = any(v["status"] in PRIMARY_VALUES for v in visits)
        if not is_primary:
            continue
        total_primary += 1
        src = visits[0]["source"]
        if src:
            sources[src] += 1
        if len(visits) > 1:
            stayed += 1
        else:
            single_visit += 1
        if any(v["referred"] for v in visits):
            referred += 1

    tp = total_primary or 1
    return {
        "total_primary": total_primary,
        "stayed":        stayed,
        "stayed_pct":    round(stayed / tp * 100),
        "referred":      referred,
        "referred_pct":  round(referred / tp * 100),
        "single_visit":  single_visit,
        "lost_pct":      round(single_visit / tp * 100),
        "top_sources":   sorted(sources.items(), key=lambda x: -x[1])[:5],
    }


# ════════════════════════════════════════════════════════════════
#  AI РЕКОМЕНДАЦИИ
# ════════════════════════════════════════════════════════════════

async def generate_recommendations(doctors: dict, flow: dict, period_days: int = 30) -> str:
    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_KEY", ""))
    except ImportError:
        return "Установи anthropic для AI-рекомендаций."

    docs_summary = []
    for doc, d in sorted(doctors.items(), key=lambda x: -x[1]["revenue"])[:10]:
        docs_summary.append(
            f"• {doc}: выручка {d['revenue']:,}₽, пациентов {d['unique_patients']}, "
            f"ср.чек {d['avg_check']:,}₽, первичных {d['primary_pct']}%, "
            f"перенаправлений {d['referred_out']}, дней работы {d['working_days']}"
        )

    prompt = f"""Ты — аналитик стоматологической клиники. Проанализируй данные за {period_days} дней.

ВРАЧИ:
{chr(10).join(docs_summary)}

ПЕРВИЧНЫЕ ПАЦИЕНТЫ:
- Всего первичных: {flow['total_primary']}
- Остались на лечение: {flow['stayed']} ({flow['stayed_pct']}%)
- Перенаправлены к другому врачу: {flow['referred']} ({flow['referred_pct']}%)
- Ушли после 1 визита: {flow['single_visit']} ({flow['lost_pct']}%)

Дай анализ:
1. ТОП-3 проблемы которые видно в цифрах
2. По каждому врачу с низкими показателями — что делать конкретно
3. Как улучшить удержание первичных (сейчас теряем {flow['lost_pct']}%)
4. 3 конкретных действия на эту неделю

Пиши кратко и конкретно. Называй врачей по имени."""

    msg = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=900,
        messages=[{"role": "user", "content": prompt}]
    )
    return msg.content[0].text.strip()


# ════════════════════════════════════════════════════════════════
#  ФОРМАТИРОВАНИЕ ДЛЯ TELEGRAM
# ════════════════════════════════════════════════════════════════

def format_doctor_report(doctors: dict, period_days: int = 30) -> str:
    if not doctors:
        return "❌ Нет данных по врачам."
    lines = [f"👨‍⚕️ *Врачи за {period_days} дней*\n"]
    total_rev = sum(d["revenue"] for d in doctors.values())
    lines.append(f"💰 Общая выручка клиники: *{total_rev:,} ₽*\n")
    medals = ["🥇", "🥈", "🥉"]
    for i, (doc, d) in enumerate(sorted(doctors.items(), key=lambda x: -x[1]["revenue"]), 1):
        m = medals[i-1] if i <= 3 else f"{i}\\."
        share = round(d["revenue"] / total_rev * 100) if total_rev else 0
        lines.append(
            f"{m} *{doc}*\n"
            f"   💵 {d['revenue']:,} ₽ ({share}% клиники) · чек {d['avg_check']:,} ₽\n"
            f"   👥 {d['unique_patients']} пациентов · {d['working_days']} дн. работы\n"
            f"   🆕 Первичных: {d['primary']} ({d['primary_pct']}%) "
            f"· 🔁 Повторных: {d['retention_pct']}%\n"
            f"   ➡️ Перенаправил: {d['referred_out']} · Принял: {d['referred_in']}\n"
        )
    return "\n".join(lines)


def format_flow_report(flow: dict, period_days: int = 30) -> str:
    if flow["total_primary"] == 0:
        return "❌ Нет данных о первичных пациентах."

    def bar(pct):
        filled = min(pct // 5, 20)
        return "█" * filled + "░" * (20 - filled)

    lines = [
        f"🔍 *Воронка первичных пациентов* за {period_days} дней\n",
        f"📥 Пришло первичных: *{flow['total_primary']}*\n",
        f"✅ Остались на лечение: *{flow['stayed']}* — {flow['stayed_pct']}%",
        f"   {bar(flow['stayed_pct'])}",
        f"➡️  Перенаправлены: *{flow['referred']}* — {flow['referred_pct']}%",
        f"❌ Ушли после 1 визита: *{flow['single_visit']}* — {flow['lost_pct']}%",
        f"   {bar(flow['lost_pct'])}",
    ]
    if flow["top_sources"]:
        lines.append("\n📊 *Источники первичных:*")
        for src, cnt in flow["top_sources"]:
            lines.append(f"   • {src or 'не указан'}: {cnt}")
    return "\n".join(lines)


# ════════════════════════════════════════════════════════════════
#  ГЛАВНЫЙ МЕТОД
# ════════════════════════════════════════════════════════════════

async def full_report(period_days: int = 30, with_ai: bool = True) -> dict:
    rows = load_shift_data(period_days)
    if not rows:
        return {"error": (
            f"❌ Нет данных за {period_days} дней.\n\n"
            "Проверь:\n"
            "1. Таблицы открыты на просмотр (Поделиться → Все у кого есть ссылка)\n"
            "2. Названия колонок совпадают с COL\\_MAP настройками\n"
            "3. В таблице есть строки с датами за этот период"
        )}
    doctors = analyze_doctors(rows)
    flow    = analyze_patient_flow(rows)
    result  = {
        "doctor_report": format_doctor_report(doctors, period_days),
        "flow_report":   format_flow_report(flow, period_days),
        "raw_doctors":   doctors,
        "raw_flow":      flow,
        "total_rows":    len(rows),
    }
    if with_ai:
        result["ai_recs"] = await generate_recommendations(doctors, flow, period_days)
    return result


if __name__ == "__main__":
    import sys
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    async def main():
        print(f"Загружаю данные за {days} дней...\n")
        r = await full_report(days)
        if "error" in r:
            print(r["error"]); return
        print(r["doctor_report"])
        print("\n" + "="*50)
        print(r["flow_report"])
        print("\n" + "="*50)
        print("AI РЕКОМЕНДАЦИИ:\n" + r.get("ai_recs", "—"))
    asyncio.run(main())
