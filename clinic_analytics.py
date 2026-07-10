"""
Аналитический модуль стоматологической клиники.
Читает Google Sheets → считает KPI → даёт рекомендации через Claude.

Листы:
  SHEET_REVENUE_MAIN   — основная клиника (Кристина, Давлат, Кисиев, Александров)
  SHEET_REVENUE_MUTOL  — Мутолиб (Бега, БИБО)
  SHEET_LEADS          — МИС: звонки/записи/визиты

Env:
  GOOGLE_CREDS_JSON    — JSON сервисного аккаунта (строка или путь)
  ANTHROPIC_KEY        — ключ Claude
"""

import os
import re
import json
import asyncio
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Optional
import anthropic

# ── Google Sheets IDs ─────────────────────────────────────────────
SHEET_REVENUE_MAIN  = "1RMlCNKvcW9YYc_S3nUyAR7Rrl9FiybhP4AFc5gUKim8"
SHEET_REVENUE_MUTOL = "1IebXYtEpJWi9rpUHGmrQk-sPJkBPN-p_dsCkoz4IFko"
SHEET_LEADS         = "1yDFRg3T50rkVgwjRd_xzPwbf62X-8eEwxayk_DaVV-o"

MODEL = "claude-sonnet-4-6"

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_KEY", ""))


# ══════════════════════════════════════════════════════════════════
#  Google Sheets reader
# ══════════════════════════════════════════════════════════════════

def _get_gc():
    """Возвращает авторизованный gspread клиент."""
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        raise RuntimeError("Установи: pip install gspread google-auth")

    creds_raw = os.getenv("GOOGLE_CREDS_JSON", "")
    if not creds_raw:
        raise RuntimeError("Нет GOOGLE_CREDS_JSON в переменных окружения")

    if creds_raw.strip().startswith("{"):
        info = json.loads(creds_raw)
    else:
        with open(creds_raw) as f:
            info = json.load(f)

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    creds = Credentials.from_service_account_info(info, scopes=scopes)
    return gspread.authorize(creds)


def read_sheet_values(sheet_id: str, sheet_index: int = 0) -> list[list]:
    """Читает все значения листа."""
    gc = _get_gc()
    sh = gc.open_by_key(sheet_id)
    ws = sh.get_worksheet(sheet_index)
    return ws.get_all_values()


# ══════════════════════════════════════════════════════════════════
#  Парсер листов выручки (формат: дата → врач → пациенты)
# ══════════════════════════════════════════════════════════════════

DATE_RE   = re.compile(r'\b(\d{2}\.\d{2}\.\d{4})\b')
DOCTOR_RE = re.compile(r'врач\s+(.+)', re.IGNORECASE)
RENT_RE   = re.compile(r'аренда', re.IGNORECASE)


def parse_revenue_sheet(rows: list[list], location: str = "") -> list[dict]:
    """
    Парсит лист выручки в список записей:
    {date, doctor, patient, amount, anesthesia, payment_type, is_rent, location}
    """
    records = []
    current_date   = None
    current_doctor = None

    for row in rows:
        cells = [str(c).strip() for c in row]
        line  = " ".join(cells).strip()
        if not line:
            continue

        # ── поиск даты ──────────────────────────────────────────
        dm = DATE_RE.search(line)
        if dm:
            current_date = dm.group(1)

        # ── поиск врача ─────────────────────────────────────────
        doc_m = DOCTOR_RE.search(line)
        if doc_m:
            current_doctor = doc_m.group(1).strip().title()
            continue

        # ── строка аренды ────────────────────────────────────────
        if RENT_RE.search(line):
            amount = _extract_amount(cells)
            if amount and current_date:
                renter = cells[0] if cells else "аренда"
                records.append({
                    "date":         current_date,
                    "doctor":       current_doctor or "—",
                    "patient":      renter,
                    "amount":       amount,
                    "anesthesia":   0,
                    "payment_type": _find_payment(cells),
                    "is_rent":      True,
                    "location":     location,
                })
            continue

        # ── строка пациента (первая ячейка — номер) ──────────────
        if cells and cells[0].isdigit() and current_date and current_doctor:
            amount = _extract_amount(cells)
            if amount:
                try:
                    anesthesia = int(cells[3]) if len(cells) > 3 and cells[3].isdigit() else 0
                except (ValueError, IndexError):
                    anesthesia = 0
                patient = cells[1] if len(cells) > 1 else "—"
                records.append({
                    "date":         current_date,
                    "doctor":       current_doctor,
                    "patient":      patient,
                    "amount":       amount,
                    "anesthesia":   anesthesia,
                    "payment_type": _find_payment(cells),
                    "is_rent":      False,
                    "location":     location,
                })

    return records


def _extract_amount(cells: list[str]) -> Optional[int]:
    for c in cells:
        c = c.replace(" ", "").replace("\xa0", "")
        if re.fullmatch(r'\d{3,6}', c):
            return int(c)
    return None


def _find_payment(cells: list[str]) -> str:
    keywords = {
        "нал": "наличные", "cash": "наличные",
        "терминал": "терминал", "terminal": "терминал",
        "перевод": "перевод", "сбер": "перевод", "альфа": "перевод",
        "карта": "перевод",
        "биглион": "биглион",
        "без оплат": "без оплаты",
    }
    joined = " ".join(cells).lower()
    for kw, label in keywords.items():
        if kw in joined:
            return label
    return "другое"


# ══════════════════════════════════════════════════════════════════
#  Парсер листа МИС (первичные пациенты)
# ══════════════════════════════════════════════════════════════════

def parse_leads_sheet(rows: list[list]) -> list[dict]:
    """
    Парсит лист МИС в список лидов.
    Ожидает заголовок: Дата|Время|Источник|Канал|Обращение|Номер|Имя|Запрос|
                        Категория|Записался|Услуга|Пришел|Срочность|Причина|Вопрос|Комментарий
    """
    leads = []
    header = None
    for row in rows:
        cells = [str(c).strip() for c in row]
        if not header:
            if "Дата" in cells and "Записался" in cells:
                header = [c.lower() for c in cells]
            continue

        if len(cells) < len(header):
            cells += [""] * (len(header) - len(cells))

        def g(name: str) -> str:
            for i, h in enumerate(header):
                if name in h:
                    return cells[i] if i < len(cells) else ""
            return ""

        date_str = g("дата")
        if not date_str or date_str.lower() == "дата":
            continue

        leads.append({
            "date":         date_str,
            "source":       g("источник"),
            "appeal_type":  g("обращение"),   # первичное / повторное
            "phone":        g("номер"),
            "name":         g("имя"),
            "request":      g("запрос"),
            "call_type":    g("категория"),   # целевой / нецелевой
            "booked":       g("записался").lower() == "да",
            "service":      g("услуга"),
            "visited":      g("пришел").lower() == "да",
            "urgency":      g("срочность"),
            "no_book_reason": g("причина"),
            "comment":      g("комментарий"),
        })

    return leads


# ══════════════════════════════════════════════════════════════════
#  KPI расчёт
# ══════════════════════════════════════════════════════════════════

def calc_revenue_kpi(records: list[dict], days: int = 7) -> dict:
    """Считает KPI выручки за последние N дней."""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%d.%m.%Y")

    doctors    = defaultdict(lambda: {"revenue": 0, "patients": 0, "checks": [], "anesthesia": 0})
    rent_total = 0
    by_payment = defaultdict(int)
    daily      = defaultdict(int)

    for r in records:
        if r["date"] < cutoff:
            continue
        amt = r["amount"]

        if r["is_rent"]:
            rent_total += amt
            continue

        doc = r["doctor"]
        doctors[doc]["revenue"]    += amt
        doctors[doc]["patients"]   += 1
        doctors[doc]["checks"].append(amt)
        doctors[doc]["anesthesia"] += r["anesthesia"]
        by_payment[r["payment_type"]] += amt
        daily[r["date"]] += amt

    # средний чек
    for doc, d in doctors.items():
        d["avg_check"] = int(sum(d["checks"]) / len(d["checks"])) if d["checks"] else 0

    total_revenue = sum(d["revenue"] for d in doctors.values()) + rent_total

    return {
        "total_revenue":  total_revenue,
        "patient_revenue": total_revenue - rent_total,
        "rent_income":    rent_total,
        "doctors":        dict(doctors),
        "by_payment":     dict(by_payment),
        "daily":          dict(daily),
        "days":           days,
    }


def calc_leads_kpi(leads: list[dict], days: int = 30) -> dict:
    """Считает воронку первичных пациентов."""
    cutoff_month = (datetime.now() - timedelta(days=days)).strftime("%m")

    filtered = [
        l for l in leads
        if l["appeal_type"].lower() == "первичное"
        and (cutoff_month in l["date"] or not l["date"])
    ]

    total       = len(filtered)
    targeted    = sum(1 for l in filtered if "целевой" in l["call_type"].lower())
    booked      = sum(1 for l in filtered if l["booked"])
    visited     = sum(1 for l in filtered if l["visited"])

    by_source: dict[str, dict] = defaultdict(lambda: {"calls": 0, "booked": 0, "visited": 0})
    for l in filtered:
        src = l["source"] or "Неизвестно"
        by_source[src]["calls"]   += 1
        by_source[src]["booked"]  += int(l["booked"])
        by_source[src]["visited"] += int(l["visited"])

    no_book_reasons = defaultdict(int)
    for l in filtered:
        if not l["booked"] and l["no_book_reason"]:
            no_book_reasons[l["no_book_reason"]] += 1

    return {
        "total_calls":     total,
        "targeted_calls":  targeted,
        "booked":          booked,
        "visited":         visited,
        "book_rate":       round(booked / total * 100, 1) if total else 0,
        "visit_rate":      round(visited / booked * 100, 1) if booked else 0,
        "by_source":       dict(by_source),
        "no_book_reasons": dict(no_book_reasons),
        "days":            days,
    }


# ══════════════════════════════════════════════════════════════════
#  Генерация отчёта через Claude
# ══════════════════════════════════════════════════════════════════

def generate_report_text(rev_kpi: dict, leads_kpi: dict) -> str:
    """Строит текстовый дайджест для промпта."""
    lines = []

    # выручка
    lines.append(f"=== ВЫРУЧКА ЗА {rev_kpi['days']} ДНЕЙ ===")
    lines.append(f"Итого: {rev_kpi['total_revenue']:,} ₽  (пациенты: {rev_kpi['patient_revenue']:,} ₽ + аренда: {rev_kpi['rent_income']:,} ₽)")
    lines.append("")
    lines.append("По врачам:")
    for doc, d in sorted(rev_kpi["doctors"].items(), key=lambda x: -x[1]["revenue"]):
        lines.append(f"  {doc}: {d['revenue']:,} ₽ | {d['patients']} пац. | ср. чек {d['avg_check']:,} ₽ | анест. {d['anesthesia']} доз")

    lines.append("")
    lines.append("Способы оплаты:")
    for pt, amt in sorted(rev_kpi["by_payment"].items(), key=lambda x: -x[1]):
        lines.append(f"  {pt}: {amt:,} ₽")

    # воронка
    lines.append("")
    lines.append(f"=== ПЕРВИЧНЫЕ ПАЦИЕНТЫ ЗА {leads_kpi['days']} ДНЕЙ ===")
    lines.append(f"Звонков: {leads_kpi['total_calls']}  |  Целевых: {leads_kpi['targeted_calls']}")
    lines.append(f"Записалось: {leads_kpi['booked']} ({leads_kpi['book_rate']}%)")
    lines.append(f"Пришло: {leads_kpi['visited']} (конверсия из записи: {leads_kpi['visit_rate']}%)")
    lines.append("")
    lines.append("Источники:")
    for src, s in sorted(leads_kpi["by_source"].items(), key=lambda x: -x[1]["calls"]):
        br = round(s["booked"] / s["calls"] * 100, 1) if s["calls"] else 0
        lines.append(f"  {src}: {s['calls']} звонков → {s['booked']} записей ({br}%) → {s['visited']} визитов")

    if leads_kpi["no_book_reasons"]:
        lines.append("")
        lines.append("Причины отказа от записи:")
        for reason, cnt in sorted(leads_kpi["no_book_reasons"].items(), key=lambda x: -x[1]):
            lines.append(f"  {reason}: {cnt}")

    return "\n".join(lines)


async def ai_recommendations(report_text: str) -> str:
    """Просит Claude проанализировать данные и дать рекомендации."""
    prompt = f"""Ты аналитик стоматологической клиники. Вот данные за период:

{report_text}

Дай конкретные рекомендации:
1. По каждому врачу — что делать чтобы увеличить выручку и средний чек
2. По воронке первичных — где теряем пациентов и как исправить
3. По источникам — куда вкладывать рекламный бюджет
4. Топ-3 приоритета на следующую неделю

Формат: коротко, по делу, конкретные цифры и действия. На русском."""

    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(None, lambda: client.messages.create(
        model=MODEL,
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}],
    ))
    return response.content[0].text.strip()


# ══════════════════════════════════════════════════════════════════
#  Главная точка входа
# ══════════════════════════════════════════════════════════════════

async def run_full_report(days_revenue: int = 7, days_leads: int = 30) -> str:
    """
    Полный отчёт: читает обе таблицы → считает KPI → AI рекомендации.
    Возвращает строку для отправки в Telegram.
    """
    try:
        # читаем листы
        rows_main  = read_sheet_values(SHEET_REVENUE_MAIN)
        rows_mutol = read_sheet_values(SHEET_REVENUE_MUTOL)
        rows_leads = read_sheet_values(SHEET_LEADS)
    except RuntimeError as e:
        return f"❌ Ошибка чтения Google Sheets: {e}"

    # парсим
    records = (
        parse_revenue_sheet(rows_main,  location="Основная")
        + parse_revenue_sheet(rows_mutol, location="Мутолиб")
    )
    leads = parse_leads_sheet(rows_leads)

    # KPI
    rev_kpi   = calc_revenue_kpi(records, days=days_revenue)
    leads_kpi = calc_leads_kpi(leads, days=days_leads)

    # текст
    report_text = generate_report_text(rev_kpi, leads_kpi)

    # AI
    ai_text = await ai_recommendations(report_text)

    # итоговый TG-отчёт
    out = []
    out.append("📊 *АНАЛИТИКА КЛИНИКИ*\n")

    out.append(f"💰 *Выручка за {days_revenue} дн:* {rev_kpi['total_revenue']:,} ₽")
    out.append(f"  └ пациенты: {rev_kpi['patient_revenue']:,} ₽")
    out.append(f"  └ аренда кресел: {rev_kpi['rent_income']:,} ₽\n")

    out.append("👨‍⚕️ *По врачам:*")
    for doc, d in sorted(rev_kpi["doctors"].items(), key=lambda x: -x[1]["revenue"]):
        out.append(f"  • {doc}: {d['revenue']:,} ₽ | {d['patients']} пац | ср.чек {d['avg_check']:,} ₽")

    out.append(f"\n📞 *Первичные пациенты (30 дн):*")
    out.append(f"  Звонков: {leads_kpi['total_calls']} → Записей: {leads_kpi['booked']} ({leads_kpi['book_rate']}%) → Визитов: {leads_kpi['visited']} ({leads_kpi['visit_rate']}%)")

    out.append("\n📡 *Источники:*")
    for src, s in sorted(leads_kpi["by_source"].items(), key=lambda x: -x[1]["calls"])[:5]:
        out.append(f"  • {src}: {s['calls']} зв → {s['visited']} визитов")

    out.append(f"\n🤖 *Рекомендации AI:*\n{ai_text}")

    return "\n".join(out)


async def doctor_report(doctor_name: str, days: int = 14) -> str:
    """Детальный отчёт по конкретному врачу."""
    try:
        rows_main  = read_sheet_values(SHEET_REVENUE_MAIN)
        rows_mutol = read_sheet_values(SHEET_REVENUE_MUTOL)
    except RuntimeError as e:
        return f"❌ {e}"

    records = (
        parse_revenue_sheet(rows_main,  "Основная")
        + parse_revenue_sheet(rows_mutol, "Мутолиб")
    )

    cutoff = (datetime.now() - timedelta(days=days)).strftime("%d.%m.%Y")
    doc_records = [
        r for r in records
        if not r["is_rent"]
        and doctor_name.lower() in r["doctor"].lower()
        and r["date"] >= cutoff
    ]

    if not doc_records:
        return f"❌ Врач '{doctor_name}' не найден или нет данных за {days} дней."

    total    = sum(r["amount"] for r in doc_records)
    patients = len(doc_records)
    avg      = total // patients if patients else 0
    by_date  = defaultdict(int)
    for r in doc_records:
        by_date[r["date"]] += r["amount"]

    out = [f"👨‍⚕️ *{doc_records[0]['doctor']}* — {days} дней\n"]
    out.append(f"💰 Выручка: {total:,} ₽")
    out.append(f"👥 Пациентов: {patients}")
    out.append(f"📊 Средний чек: {avg:,} ₽\n")
    out.append("📅 По дням:")
    for date in sorted(by_date)[-7:]:
        out.append(f"  {date}: {by_date[date]:,} ₽")

    # AI рекомендация
    prompt = f"Врач {doc_records[0]['doctor']}: выручка {total:,} ₽, {patients} пациентов, средний чек {avg:,} ₽ за {days} дней. Дай 3 конкретных совета как увеличить показатели."
    loop = asyncio.get_event_loop()
    ai = await loop.run_in_executor(None, lambda: client.messages.create(
        model=MODEL, max_tokens=400,
        messages=[{"role": "user", "content": prompt}]
    ))
    out.append(f"\n🤖 *AI совет:*\n{ai.content[0].text.strip()}")

    return "\n".join(out)


async def primary_patients_report() -> str:
    """Отчёт по первичным пациентам: пришёл/не пришёл, причины."""
    try:
        rows_leads = read_sheet_values(SHEET_LEADS)
    except RuntimeError as e:
        return f"❌ {e}"

    leads = parse_leads_sheet(rows_leads)
    kpi   = calc_leads_kpi(leads, days=30)

    out = ["🏥 *ПЕРВИЧНЫЕ ПАЦИЕНТЫ (30 дней)*\n"]
    out.append(f"📞 Всего звонков: {kpi['total_calls']}")
    out.append(f"🎯 Целевых: {kpi['targeted_calls']}")
    out.append(f"✅ Записалось: {kpi['booked']} ({kpi['book_rate']}%)")
    out.append(f"🚶 Пришло: {kpi['visited']} ({kpi['visit_rate']}% из записавшихся)\n")

    out.append("📡 *По источникам:*")
    for src, s in sorted(kpi["by_source"].items(), key=lambda x: -x[1]["visited"]):
        rate = round(s["visited"] / s["calls"] * 100, 1) if s["calls"] else 0
        out.append(f"  • {src}")
        out.append(f"    {s['calls']} зв → {s['booked']} зап → {s['visited']} визитов ({rate}%)")

    if kpi["no_book_reasons"]:
        out.append("\n❌ *Причины отказа от записи:*")
        for reason, cnt in sorted(kpi["no_book_reasons"].items(), key=lambda x: -x[1]):
            out.append(f"  • {reason}: {cnt} чел.")

    lost = kpi["booked"] - kpi["visited"]
    if lost > 0:
        prompt = f"Стоматология: из {kpi['booked']} записавшихся первичных пациентов не пришли {lost} ({100-kpi['visit_rate']}%). Как снизить процент неявок? Дай 3 конкретных действия."
        loop = asyncio.get_event_loop()
        ai = await loop.run_in_executor(None, lambda: client.messages.create(
            model=MODEL, max_tokens=350,
            messages=[{"role": "user", "content": prompt}]
        ))
        out.append(f"\n🤖 *Как вернуть не пришедших:*\n{ai.content[0].text.strip()}")

    return "\n".join(out)
