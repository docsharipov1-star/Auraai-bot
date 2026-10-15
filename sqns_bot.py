"""
Раздел бота «📅 Запись SQNS» (только для ADMIN_ID).

  ➕ Записать пациента: врач → услуга → дата → время → ФИО → телефон → подтверждение
  📆 Записи на сегодня / завтра (с отменой визита)
  🔎 Найти клиента по телефону
  🔗 Подключить вебхук (визиты из CRM → автозвонки clinic_patients)

Подключение в main(): dp.include_router(sqns_bot.router) ДО основного роутера.
"""

import os
import re
import logging
from datetime import date, datetime, timedelta
from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from sqns_client import (
    sqns, SQNSError, ATTENDANCE, SQNS_HOOK_SECRET,
    is_configured, hook_url, format_phone, resource_name,
)

log = logging.getLogger("sqns_bot")

ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
MENU_BUTTON = "📅 Запись SQNS"
DAYS_AHEAD = 14
WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
# кнопки основного меню — не принимаем их за ввод, отдаём основному роутеру
PASS_THROUGH = {"❌ Отмена", "🏠 В главное меню"}

router = Router()
router.message.filter(F.from_user.id == ADMIN_ID)
router.callback_query.filter(F.from_user.id == ADMIN_ID)


class SQNSState(StatesGroup):
    name  = State()  # ФИО пациента
    phone = State()  # телефон пациента
    find  = State()  # телефон для поиска клиента


# ── helpers ──────────────────────────────────────────────────────────────────

def _menu_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Записать пациента",  callback_data="sqb:new")
    kb.button(text="📆 Сегодня",            callback_data="sqb:day:0")
    kb.button(text="📆 Завтра",             callback_data="sqb:day:1")
    kb.button(text="🔎 Найти клиента",      callback_data="sqb:find")
    kb.button(text="🔗 Подключить вебхук",  callback_data="sqb:hook")
    kb.adjust(1, 2, 1, 1)
    return kb.as_markup()


def _cancel_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="✖️ Отмена", callback_data="sqb:cancel")
    return kb.as_markup()


def _time(dt_iso: str) -> str:
    """'2022-08-25T16:45:00+05:00' / '2023-11-07 14:00:00' → '16:45'."""
    m = re.search(r"[T ](\d{2}:\d{2})", dt_iso or "")
    return m.group(1) if m else dt_iso


def _day_label(d: date) -> str:
    return f"{d.strftime('%d.%m')} {WEEKDAYS[d.weekday()]}"


def _fmt_price(service: dict) -> str:
    rng = (service.get("price") or {}).get("range") or []
    if not rng:
        return ""
    lo, hi = (float(x) for x in (rng[0], rng[-1]))
    return f"{lo:,.0f} ₽".replace(",", " ") if lo == hi else \
        f"{lo:,.0f}–{hi:,.0f} ₽".replace(",", " ")


async def _show(target, text: str, kb=None):
    """Редактирует сообщение callback'а или отправляет новое."""
    if isinstance(target, CallbackQuery):
        try:
            await target.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
            return
        except Exception:
            target = target.message
    await target.answer(text, parse_mode="HTML", reply_markup=kb)


async def _error(target, e: Exception):
    log.warning(f"SQNS: {e}")
    await _show(target, f"❌ {escape(str(e))}", _back_kb())


def _back_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="◀️ Меню SQNS", callback_data="sqb:menu")
    return kb.as_markup()


# ── меню ─────────────────────────────────────────────────────────────────────

@router.message(F.text == MENU_BUTTON)
@router.message(Command("sqns"))
async def sqns_menu(message: Message, state: FSMContext):
    await state.clear()
    if not is_configured():
        await message.answer(
            "⚙️ <b>SQNS не настроен</b>\n\nДобавь в .env:\n"
            "<code>SQNS_BASE_URL=https://...</code>\n"
            "<code>SQNS_EMAIL=почта интегратора</code>\n"
            "<code>SQNS_PASSWORD=пароль</code>\n"
            "<code>SQNS_HOOK_SECRET=случайная строка</code>",
            parse_mode="HTML")
        return
    await message.answer("📅 <b>Запись SQNS</b>", parse_mode="HTML", reply_markup=_menu_kb())


@router.callback_query(F.data == "sqb:menu")
@router.callback_query(F.data == "sqb:cancel")
async def cb_menu(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await state.clear()
    await _show(call, "📅 <b>Запись SQNS</b>", _menu_kb())


# ── запись: врач → услуга → дата → время ─────────────────────────────────────

@router.callback_query(F.data == "sqb:new")
async def cb_new(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await state.clear()
    try:
        resources = await sqns.resources()
    except SQNSError as e:
        return await _error(call, e)
    if not resources:
        return await _show(call, "Нет сотрудников, доступных для онлайн-записи.", _back_kb())
    kb = InlineKeyboardBuilder()
    for r in resources:
        title = r.get("title", "?")
        if r.get("description"):
            title += f" · {r['description']}"
        kb.button(text=title[:60], callback_data=f"sqb:res:{r['id']}")
    kb.button(text="◀️ Назад", callback_data="sqb:menu")
    kb.adjust(1)
    await state.update_data(res_names={str(r["id"]): r.get("title", "") for r in resources})
    await _show(call, "👨‍⚕️ <b>Шаг 1/6.</b> Выбери врача:", kb.as_markup())


@router.callback_query(F.data.startswith("sqb:res:"))
async def cb_resource(call: CallbackQuery, state: FSMContext):
    await call.answer()
    rid = call.data.split(":", 2)[2]
    try:
        services = await sqns.booking_services()
    except SQNSError as e:
        return await _error(call, e)
    services = [s for s in services
                if any(str(r.get("id")) == rid for r in s.get("resources") or [])]
    data = await state.get_data()
    doctor = data.get("res_names", {}).get(rid, "")
    if not services:
        return await _show(call, f"У врача {escape(doctor)} нет услуг для онлайн-записи.", _back_kb())
    kb = InlineKeyboardBuilder()
    for s in services[:40]:
        mins = int(s.get("durationSeconds") or 0) // 60
        label = f"{s.get('title', '?')} · {mins} мин"
        price = _fmt_price(s)
        if price:
            label += f" · {price}"
        kb.button(text=label[:60], callback_data=f"sqb:svc:{s['id']}")
    kb.button(text="◀️ Назад", callback_data="sqb:new")
    kb.adjust(1)
    await state.update_data(
        resource_id=rid, doctor=doctor,
        svc_names={str(s["id"]): s.get("title", "") for s in services},
    )
    await _show(call, f"👨‍⚕️ {escape(doctor)}\n\n🦷 <b>Шаг 2/6.</b> Выбери услугу:", kb.as_markup())


@router.callback_query(F.data.startswith("sqb:svc:"))
async def cb_service(call: CallbackQuery, state: FSMContext):
    await call.answer()
    sid = call.data.split(":", 2)[2]
    data = await state.get_data()
    rid = data.get("resource_id")
    if not rid:
        return await cb_new(call, state)
    today = date.today()
    try:
        dates = await sqns.available_dates(rid, [sid], today, today + timedelta(days=DAYS_AHEAD))
    except SQNSError as e:
        return await _error(call, e)
    service = data.get("svc_names", {}).get(sid, "")
    await state.update_data(service_id=sid, service=service)
    if not dates:
        return await _show(
            call, f"Нет свободных дат на {DAYS_AHEAD} дней для «{escape(service)}».", _back_kb())
    kb = InlineKeyboardBuilder()
    for d in dates:
        kb.button(text=_day_label(date.fromisoformat(d)), callback_data=f"sqb:date:{d}")
    kb.button(text="◀️ Назад", callback_data=f"sqb:res:{rid}")
    kb.adjust(*([3] * ((len(dates) + 2) // 3)), 1)
    await _show(call,
                f"👨‍⚕️ {escape(data.get('doctor', ''))}\n🦷 {escape(service)}\n\n"
                f"📅 <b>Шаг 3/6.</b> Выбери дату:", kb.as_markup())


@router.callback_query(F.data.startswith("sqb:date:"))
async def cb_date(call: CallbackQuery, state: FSMContext):
    await call.answer()
    day = date.fromisoformat(call.data.split(":", 2)[2])
    data = await state.get_data()
    rid, sid = data.get("resource_id"), data.get("service_id")
    if not (rid and sid):
        return await cb_new(call, state)
    try:
        slots = await sqns.time_slots(rid, [sid], day)
    except SQNSError as e:
        return await _error(call, e)
    if not slots:
        return await _show(call, f"На {_day_label(day)} свободного времени нет.", _back_kb())
    await state.update_data(day=day.isoformat(), slots=slots)
    kb = InlineKeyboardBuilder()
    for i, s in enumerate(slots):
        kb.button(text=_time(s), callback_data=f"sqb:time:{i}")
    kb.button(text="◀️ Назад", callback_data=f"sqb:svc:{sid}")
    kb.adjust(*([4] * ((len(slots) + 3) // 4)), 1)
    await _show(call,
                f"👨‍⚕️ {escape(data.get('doctor', ''))}\n🦷 {escape(data.get('service', ''))}\n"
                f"📅 {_day_label(day)}\n\n🕐 <b>Шаг 4/6.</b> Выбери время:", kb.as_markup())


@router.callback_query(F.data.startswith("sqb:time:"))
async def cb_time(call: CallbackQuery, state: FSMContext):
    await call.answer()
    data = await state.get_data()
    slots = data.get("slots") or []
    idx = int(call.data.split(":", 2)[2])
    if idx >= len(slots):
        return await cb_new(call, state)
    await state.update_data(dt=slots[idx])
    await state.set_state(SQNSState.name)
    await _show(call, "👤 <b>Шаг 5/6.</b> Введи ФИО пациента:", _cancel_kb())


# ── запись: ФИО → телефон → подтверждение ────────────────────────────────────

@router.message(SQNSState.name, F.text, ~F.text.startswith("/"), ~F.text.in_(PASS_THROUGH))
async def st_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip()[:100])
    await state.set_state(SQNSState.phone)
    await message.answer("📱 <b>Шаг 6/6.</b> Телефон пациента (например 89161234567):",
                         parse_mode="HTML", reply_markup=_cancel_kb())


@router.message(SQNSState.phone, F.text, ~F.text.startswith("/"), ~F.text.in_(PASS_THROUGH))
async def st_phone(message: Message, state: FSMContext):
    if len(re.sub(r"\D", "", message.text)) not in (10, 11):
        await message.answer("Номер не распознан. Введи 10–11 цифр, например 89161234567:",
                             reply_markup=_cancel_kb())
        return
    phone = format_phone(message.text)
    await state.update_data(phone=phone)
    await state.set_state(None)
    d = await state.get_data()

    existing = ""
    try:
        client = await sqns.client_by_phone(phone)
        if client:
            existing = (f"\n\nℹ️ Клиент уже есть в CRM: <b>{escape(client.get('name', ''))}</b> "
                        f"— визит привяжется к нему.")
    except SQNSError:
        pass

    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Записать", callback_data="sqb:ok")
    kb.button(text="✖️ Отмена",   callback_data="sqb:cancel")
    kb.adjust(2)
    await message.answer(
        "📝 <b>Проверь запись</b>\n\n"
        f"👤 {escape(d['name'])}\n📱 {escape(phone)}\n"
        f"👨‍⚕️ {escape(d.get('doctor', ''))}\n🦷 {escape(d.get('service', ''))}\n"
        f"📅 {_day_label(date.fromisoformat(d['day']))} в {_time(d['dt'])}" + existing,
        parse_mode="HTML", reply_markup=kb.as_markup())


@router.callback_query(F.data == "sqb:ok")
async def cb_confirm(call: CallbackQuery, state: FSMContext):
    await call.answer()
    d = await state.get_data()
    if not all(d.get(k) for k in ("name", "phone", "resource_id", "service_id", "dt")):
        await state.clear()
        return await _show(call, "Данные записи потерялись — начни заново.", _back_kb())
    try:
        visit = await sqns.create_visit(
            name=d["name"], phone=d["phone"], resource_id=d["resource_id"],
            service_ids=[d["service_id"]], dt=d["dt"], comment="Запись через AuraAI бот",
        )
    except SQNSError as e:
        return await _error(call, e)
    await state.clear()
    await _show(call,
                f"✅ <b>Пациент записан!</b> (визит #{visit.get('id', '?')})\n\n"
                f"👤 {escape(d['name'])} · {escape(d['phone'])}\n"
                f"👨‍⚕️ {escape(d.get('doctor', ''))}\n🦷 {escape(d.get('service', ''))}\n"
                f"📅 {_day_label(date.fromisoformat(d['day']))} в {_time(d['dt'])}",
                _back_kb())


# ── записи на день + отмена ──────────────────────────────────────────────────

@router.callback_query(F.data.startswith("sqb:day:"))
async def cb_day(call: CallbackQuery):
    await call.answer()
    day = date.today() + timedelta(days=int(call.data.split(":")[2]))
    try:
        visits = await sqns.visits(day, day)
    except SQNSError as e:
        return await _error(call, e)
    visits = sorted((v for v in visits if not v.get("deleted")),
                    key=lambda v: str(v.get("datetime", "")))
    if not visits:
        return await _show(call, f"📆 {_day_label(day)}: записей нет.", _back_kb())

    lines = [f"📆 <b>Записи на {_day_label(day)}</b> ({len(visits)})\n"]
    kb = InlineKeyboardBuilder()
    for v in visits[:40]:
        c = v.get("clientData") or {}
        svc = ", ".join(s.get("name", "") for s in v.get("services") or []) or "—"
        doctor = await resource_name(v.get("resourceId"))
        status = ATTENDANCE.get(v.get("attendance"), "")
        lines.append(
            f"🕐 <b>{_time(str(v.get('datetime', '')))}</b> {escape(c.get('name', '—'))}"
            f" · {escape(c.get('phone', ''))}\n"
            f"   {escape(svc)}" + (f" · {escape(doctor)}" if doctor else "") +
            (f" · <i>{status}</i>" if status else "")
        )
        if v.get("attendance") != 1:
            kb.button(text=f"❌ {_time(str(v.get('datetime', '')))} {c.get('name', '')}"[:60],
                      callback_data=f"sqb:del:{v['id']}")
    kb.button(text="◀️ Меню SQNS", callback_data="sqb:menu")
    kb.adjust(1)
    await _show(call, "\n".join(lines)[:4000], kb.as_markup())


@router.callback_query(F.data.startswith("sqb:del:"))
async def cb_delete_ask(call: CallbackQuery):
    await call.answer()
    vid = call.data.split(":")[2]
    kb = InlineKeyboardBuilder()
    kb.button(text="🗑 Да, отменить визит", callback_data=f"sqb:delok:{vid}")
    kb.button(text="◀️ Нет",                callback_data="sqb:menu")
    kb.adjust(1)
    await _show(call, f"Отменить визит #{vid}? Он будет удалён из CRM.", kb.as_markup())


@router.callback_query(F.data.startswith("sqb:delok:"))
async def cb_delete(call: CallbackQuery):
    await call.answer()
    vid = int(call.data.split(":")[2])
    try:
        await sqns.cancel_visit(vid)
    except SQNSError as e:
        return await _error(call, e)
    await _show(call, f"🗑 Визит #{vid} отменён.", _back_kb())


# ── поиск клиента ────────────────────────────────────────────────────────────

@router.callback_query(F.data == "sqb:find")
async def cb_find(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await state.set_state(SQNSState.find)
    await _show(call, "🔎 Введи телефон клиента:", _cancel_kb())


@router.message(SQNSState.find, F.text, ~F.text.startswith("/"), ~F.text.in_(PASS_THROUGH))
async def st_find(message: Message, state: FSMContext):
    await state.clear()
    try:
        c = await sqns.client_by_phone(message.text)
    except SQNSError as e:
        return await _error(message, e)
    if not c:
        await message.answer("Клиент не найден.", reply_markup=_back_kb())
        return
    lines = [
        f"👤 <b>{escape(c.get('name', ''))}</b> (id {c.get('id')})",
        f"📱 {escape(c.get('phone', ''))}",
    ]
    if c.get("birthDate"):
        lines.append(f"🎂 {escape(c['birthDate'])}")
    if c.get("visitsCount") is not None:
        lines.append(f"🗓 Визитов: {c['visitsCount']}")
    if c.get("totalArrival"):
        lines.append(f"💵 Оплачено всего: {escape(str(c['totalArrival']))} ₽")
    if c.get("comment"):
        lines.append(f"💬 {escape(c['comment'])}")
    await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=_back_kb())


# ── вебхук ───────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "sqb:hook")
async def cb_hook_ask(call: CallbackQuery):
    await call.answer()
    if not SQNS_HOOK_SECRET:
        return await _show(call, "Сначала задай <code>SQNS_HOOK_SECRET</code> в .env.", _back_kb())
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Подключить", callback_data="sqb:hookok")
    kb.button(text="◀️ Назад",     callback_data="sqb:menu")
    kb.adjust(2)
    await _show(call,
                "🔗 <b>Вебхук SQNS</b>\n\n"
                "CRM будет присылать визиты на сервер бота. Визиты со статусом "
                "«клиент пришёл» автоматически попадут в 📋 Пациенты → автозвонки.\n\n"
                "⚠️ SQNS <b>заменяет весь список</b> хуков организации — "
                "если там подключены другие интеграции, они отвалятся.",
                kb.as_markup())


@router.callback_query(F.data == "sqb:hookok")
async def cb_hook(call: CallbackQuery):
    await call.answer()
    try:
        await sqns.set_hooks([hook_url()])
    except SQNSError as e:
        return await _error(call, e)
    await _show(call, "✅ Вебхук подключён.", _back_kb())
