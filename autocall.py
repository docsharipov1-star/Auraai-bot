"""
Автозвонки через Mango Office VPBX API.
Документация: https://www.mango-office.ru/support/virtualnyy-ofis/integracii/api/
"""

import os
import hashlib
import json
import logging
import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/autocall")


@router.post("/event")
async def mango_event(request: Request):
    """Webhook для событий Mango Office (входящие уведомления о звонках)."""
    try:
        data = await request.json()
    except Exception:
        data = {}
    log.info(f"Mango event: {data}")
    return JSONResponse({"ok": True})


@router.post("/audio")
async def mango_audio(request: Request):
    """Webhook для аудио событий Mango Office."""
    return JSONResponse({"ok": True})

log = logging.getLogger("autocall")

MANGO_API_KEY  = os.getenv("MANGO_API_KEY", "")
MANGO_API_SALT = os.getenv("MANGO_API_SALT", "")
MANGO_FROM_EXT  = os.getenv("MANGO_FROM_EXT", "")   # добавочный номер сотрудника (extension)
MANGO_FROM_NUM  = os.getenv("MANGO_FROM_NUM", "")   # исходящий номер клиники (fallback)

MANGO_BASE = "https://app.mango-office.ru/vpbx"


def _sign(json_str: str) -> str:
    """SHA256(api_key + json + api_salt)"""
    raw = MANGO_API_KEY + json_str + MANGO_API_SALT
    return hashlib.sha256(raw.encode()).hexdigest()


def _normalize_phone(phone: str) -> str:
    digits = "".join(c for c in phone if c.isdigit())
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    return digits


async def call_patient(
    phone: str,
    patient_name: str = "",
    call_type: str = "wellbeing",
    date_str: str = "",
    time_str: str = "",
) -> bool:
    """
    Инициирует исходящий звонок пациенту через Mango Office Callback API.
    Mango сначала звонит на номер клиники (from), потом соединяет с пациентом (to).
    Возвращает True если звонок принят системой.
    """
    if not MANGO_API_KEY:
        log.warning("MANGO_API_KEY не задан — звонки не работают")
        return False

    digits = _normalize_phone(phone)
    if not digits:
        log.warning(f"Некорректный номер: {phone}")
        return False

    # Выбираем источник звонка: extension (SIP) или number (внешний номер)
    if MANGO_FROM_EXT:
        from_field = {"extension": MANGO_FROM_EXT}
    elif MANGO_FROM_NUM:
        from_field = {"number": _normalize_phone(MANGO_FROM_NUM)}
    else:
        log.warning("Нужен MANGO_FROM_EXT или MANGO_FROM_NUM")
        return False

    payload = {
        "from": from_field,
        "to":   {"number": digits},
        "commandId": f"aura_{call_type}_{digits[-4:]}",
    }

    json_str = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    sign = _sign(json_str)

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{MANGO_BASE}/commands/callback",
                data={
                    "vpbx_api_key": MANGO_API_KEY,
                    "sign":         sign,
                    "json":         json_str,
                },
            )
        data = {}
        try:
            data = resp.json()
        except Exception:
            pass

        success = resp.status_code == 200 and data.get("result", -1) == 0
        if success:
            log.info(f"Звонок инициирован → {patient_name} ({phone}) [{call_type}]")
            # Регистрируем в голосовом боте чтобы связать с входящим SIP
            try:
                from voice_bot import register_call
                command_id = payload["commandId"]
                register_call(command_id, patient_name, call_type)
            except Exception:
                pass
        else:
            log.warning(f"Mango ответил: {resp.status_code} | {resp.text[:200]}")
        return success

    except Exception as e:
        log.error(f"Mango call error: {e}")
        return False


async def send_sms(phone: str, text: str) -> bool:
    """Отправка SMS через Mango Office."""
    if not MANGO_API_KEY:
        return False

    digits = _normalize_phone(phone)
    if not digits:
        return False

    payload = {
        "message": {
            "to":   {"number": digits},
            "text": text[:160],
        }
    }
    json_str = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    sign = _sign(json_str)

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{MANGO_BASE}/sms/send",
                data={
                    "vpbx_api_key": MANGO_API_KEY,
                    "sign":         sign,
                    "json":         json_str,
                },
            )
        success = resp.status_code == 200
        log.info(f"SMS → {phone}: {'OK' if success else resp.text[:100]}")
        return success
    except Exception as e:
        log.error(f"Mango SMS error: {e}")
        return False
