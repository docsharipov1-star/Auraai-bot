"""
Клиент SQNS CRM Exchange API v2 (Arnica / Denta / Clinica).

Возможности:
  • авторизация (JWT, автообновление при 401)
  • онлайн-запись: сотрудники, услуги, свободные даты/слоты,
    создание / перенос / отмена визита, поиск клиента
  • выгрузка: визиты, клиенты, услуги, товары (с пагинацией)
  • вебхуки: подписка + приёмник /sqns/hook/{secret}
    (пришедшие визиты попадают в clinic_patients → автозвонки по расписанию)

.env:
  SQNS_BASE_URL=https://bookingapi.arnica.pro   # уточнить у поддержки SQNS
  SQNS_EMAIL=integrator@clinic.ru               # почта сотрудника-интегратора
  SQNS_PASSWORD=...
  SQNS_HOOK_SECRET=длинная-случайная-строка     # часть URL вебхука
"""

import os
import re
import asyncio
import logging
from datetime import date, datetime
from typing import AsyncIterator, Optional

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

log = logging.getLogger("sqns")

SQNS_BASE_URL    = os.getenv("SQNS_BASE_URL", "https://bookingapi.arnica.pro").rstrip("/")
SQNS_EMAIL       = os.getenv("SQNS_EMAIL", "")
SQNS_PASSWORD    = os.getenv("SQNS_PASSWORD", "")
SQNS_HOOK_SECRET = os.getenv("SQNS_HOOK_SECRET", "")
BASE_URL         = os.getenv("BASE_URL", "https://auraai-bot-production.up.railway.app").rstrip("/")

PAGE_SIZE = 100  # больше 100 SQNS не рекомендует

# attendance визита
ATTENDANCE = {
    -1: "отменён",
    0:  "не подтверждён",
    1:  "клиент пришёл",
    2:  "подтверждён",
}


class SQNSError(Exception):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


def is_configured() -> bool:
    return bool(SQNS_EMAIL and SQNS_PASSWORD)


def hook_url() -> str:
    return f"{BASE_URL}/sqns/hook/{SQNS_HOOK_SECRET}"


def format_phone(raw: str) -> str:
    """Любой российский номер → формат SQNS: +7(999)587-00-11."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 10:
        digits = "7" + digits
    elif len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    if len(digits) != 11:
        return raw
    return f"+{digits[0]}({digits[1:4]}){digits[4:7]}-{digits[7:9]}-{digits[9:11]}"


# ── HTTP-клиент ───────────────────────────────────────────────────────────────

class SQNSClient:
    def __init__(self, base_url: str = SQNS_BASE_URL,
                 email: str = SQNS_EMAIL, password: str = SQNS_PASSWORD):
        self.base_url = base_url
        self.email    = email
        self.password = password
        self._token: Optional[str] = None
        self._lock  = asyncio.Lock()
        self._http: Optional[httpx.AsyncClient] = None

    def _client(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            # выгрузка у SQNS может идти до ~60 сек
            self._http = httpx.AsyncClient(base_url=self.base_url, timeout=70)
        return self._http

    async def close(self):
        if self._http and not self._http.is_closed:
            await self._http.aclose()

    # ── авторизация ──

    async def auth(self) -> str:
        if not (self.email and self.password):
            raise SQNSError("SQNS_EMAIL / SQNS_PASSWORD не заданы")
        r = await self._client().post(
            "/api/v1/auth", json={"email": self.email, "password": self.password}
        )
        data = self._parse(r)
        token = data.get("token")
        if not token:
            raise SQNSError(f"SQNS auth: нет токена в ответе: {data}", r.status_code)
        self._token = token
        log.info(f"SQNS: авторизован как {data.get('user', {}).get('name', self.email)}")
        return token

    async def _ensure_token(self) -> str:
        async with self._lock:
            if not self._token:
                await self.auth()
            return self._token

    async def request(self, method: str, path: str, *,
                      params: dict = None, json: dict = None) -> dict:
        token = await self._ensure_token()
        for attempt in range(2):
            r = await self._client().request(
                method, path, params=params, json=json,
                headers={"Authorization": f"Bearer {token}"},
            )
            # токен протух / невалиден → один раз перелогиниваемся
            if r.status_code == 401 and attempt == 0 and "deactivated" not in r.text:
                async with self._lock:
                    self._token = None
                token = await self._ensure_token()
                continue
            return self._parse(r)
        return {}

    @staticmethod
    def _parse(r: httpx.Response) -> dict:
        try:
            data = r.json() if r.content else {}
        except ValueError:
            data = {"raw": r.text[:500]}
        if r.status_code >= 400:
            msg = ""
            if isinstance(data, dict):
                msg = data.get("message") or data.get("error") or data.get("raw") or ""
            if r.status_code == 401 and "deactivated" in r.text:
                msg = "ключ API деактивирован — обратитесь в поддержку SQNS"
            raise SQNSError(f"SQNS {r.status_code}: {msg or r.reason_phrase}", r.status_code)
        return data if isinstance(data, dict) else {"data": data}

    # ── онлайн-запись ──

    async def resources(self) -> list[dict]:
        """Сотрудники, доступные для онлайн-записи."""
        return (await self.request("GET", "/api/v2/resource")).get("resources", [])

    async def booking_services(self) -> list[dict]:
        """Услуги онлайн-записи (с длительностью и привязанными сотрудниками)."""
        return (await self.request("GET", "/api/v2/booking/service")).get("services", [])

    async def booking_service(self, service_id: str) -> dict:
        return (await self.request("GET", f"/api/v2/booking/service/{service_id}")).get("service", {})

    async def available_dates(self, resource_id: str, service_ids: list[str],
                              date_from: date, date_to: date) -> list[str]:
        data = await self.request(
            "GET", f"/api/v2/resource/{resource_id}/date",
            params={"serviceIds[]": service_ids,
                    "from": date_from.isoformat(), "to": date_to.isoformat()},
        )
        return [d["date"] for d in data.get("availableDates", [])]

    async def time_slots(self, resource_id: str, service_ids: list[str], day: date) -> list[str]:
        """Свободное время, ISO с часовым поясом: 2022-08-25T16:45:00+05:00."""
        data = await self.request(
            "GET", f"/api/v2/resource/{resource_id}/time",
            params={"serviceIds[]": service_ids, "date": day.isoformat()},
        )
        return [s["datetime"] for s in data.get("availableTimeSlots", [])]

    async def create_visit(self, *, name: str, phone: str, resource_id: str,
                           service_ids: list[str], dt: str,
                           email: str = "", comment: str = "") -> dict:
        """Создаёт визит. Клиент с таким телефоном привяжется автоматически."""
        user = {"name": name, "phone": phone}
        if email:
            user["email"] = email
        data = await self.request("POST", "/api/v2/visit", json={"visit": {
            "user": user,
            "comment": comment,
            "appointment": {
                "serviceIds": [str(s) for s in service_ids],
                "resourceId": str(resource_id),
                "datetime": dt,
            },
        }})
        return data.get("visit", data)

    async def update_visit(self, visit_id: int, *, dt: str = None, comment: str = None) -> dict:
        """Перенос / смена комментария. Прошедшие и «клиент пришёл» менять нельзя."""
        body = {}
        if dt:
            body["datetime"] = dt
        if comment is not None:
            body["comment"] = comment
        data = await self.request("PUT", f"/api/v2/visit/{visit_id}", json=body)
        return data.get("visit", data)

    async def cancel_visit(self, visit_id: int) -> dict:
        """Удаление визита. Прошедшие и «клиент пришёл» удалять нельзя."""
        return await self.request("DELETE", f"/api/v2/visit/{visit_id}")

    async def client_by_phone(self, phone: str) -> Optional[dict]:
        try:
            data = await self.request("GET", f"/api/v2/client/phone/{format_phone(phone)}")
        except SQNSError as e:
            if e.status == 404:
                return None
            raise
        return data.get("client")

    async def client_by_id(self, client_id: int) -> Optional[dict]:
        return (await self.request("GET", f"/api/v2/client/{client_id}")).get("client")

    # ── выгрузка ──

    async def _paginate(self, path: str, params: dict = None) -> AsyncIterator[dict]:
        page = 1
        while True:
            p = dict(params or {})
            # в документации параметр назван «peerPage» — шлём оба варианта
            p.update({"page": page, "perPage": PAGE_SIZE, "peerPage": PAGE_SIZE})
            data = await self.request("GET", path, params=p)
            for item in data.get("data", []):
                yield item
            meta = data.get("meta") or {}
            if page >= int(meta.get("lastPage") or 1):
                break
            page += 1

    async def visits(self, date_from: date, date_till: date) -> list[dict]:
        return [v async for v in self._paginate(
            "/api/v2/visit",
            {"dateFrom": date_from.isoformat(), "dateTill": date_till.isoformat()},
        )]

    async def clients(self) -> list[dict]:
        return [c async for c in self._paginate("/api/v2/client")]

    async def services(self) -> list[dict]:
        return [s async for s in self._paginate("/api/v2/service")]

    async def commodities(self) -> list[dict]:
        return [c async for c in self._paginate("/api/v2/commodity")]

    # ── вебхуки ──

    async def set_hooks(self, urls: list[str]) -> dict:
        """ВНИМАНИЕ: заменяет весь список хуков организации."""
        return await self.request("POST", "/api/v2/hook_settings", json={"urls": urls})


sqns = SQNSClient()


# ── Приёмник вебхуков ─────────────────────────────────────────────────────────

router = APIRouter(prefix="/sqns")

_resource_names: dict[str, str] = {}


async def resource_name(resource_id) -> str:
    rid = str(resource_id or "")
    if rid and rid not in _resource_names:
        try:
            for r in await sqns.resources():
                _resource_names[str(r["id"])] = r.get("title", "")
        except Exception as e:
            log.warning(f"SQNS resources: {e}")
    return _resource_names.get(rid, "")


async def sync_visit_to_patients(visit: dict) -> Optional[int]:
    """Визит, на который клиент пришёл → clinic_patients (для автозвонков)."""
    if visit.get("deleted") or visit.get("attendance") != 1:
        return None
    client = visit.get("clientData") or {}
    phone_raw = client.get("phone") or ""
    if len(re.sub(r"\D", "", phone_raw)) < 10:
        return None
    try:
        visit_day = datetime.strptime(str(visit.get("datetime", ""))[:10], "%Y-%m-%d").date()
    except ValueError:
        return None

    from clinic_patients import init_db, add_patient, patient_exists, normalize_phone
    phone = normalize_phone(phone_raw)
    await init_db()
    if await patient_exists(phone, visit_day):
        return None
    doctor = await resource_name(visit.get("resourceId"))
    pid = await add_patient(name=client.get("name") or "Пациент", phone=phone,
                            doctor=doctor, visit_date=visit_day)
    log.info(f"SQNS → clinic_patients: {client.get('name')} {phone} {visit_day} (id={pid})")
    return pid


@router.post("/hook/{secret}")
async def sqns_hook(secret: str, request: Request):
    if not SQNS_HOOK_SECRET or secret != SQNS_HOOK_SECRET:
        return JSONResponse({"ok": False}, status_code=403)
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "bad json"}, status_code=400)

    obj = data.get("object")
    log.info(f"SQNS hook: {obj}/{data.get('type')} org={data.get('orgId')}")
    if obj == "visit":
        try:
            await sync_visit_to_patients(data.get("visit") or {})
        except Exception as e:
            log.error(f"SQNS hook visit sync: {e}")
    return JSONResponse({"ok": True})
