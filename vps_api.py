#!/usr/bin/env python3
"""
Мини-API на VPS для управления сервисами через Telegram.
Запуск: uvicorn vps_api:app --host 0.0.0.0 --port 9090
"""

import os
import subprocess
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

app = FastAPI()
SECRET = os.getenv("SERVER_API_SECRET", "alina_vps_2024")

SAFE_COMMANDS = {
    "logs":     "journalctl -u alina -n 40 --no-pager",
    "status":   "systemctl status alina asterisk --no-pager",
    "restart":  "systemctl restart alina && echo OK",
    "restart_asterisk": "systemctl restart asterisk && echo OK",
    "resources": "echo '=== RAM ===' && free -h && echo '=== DISK ===' && df -h / && echo '=== CPU ===' && top -bn1 | head -5",
    "uptime":   "uptime",
    "calls":    "asterisk -rx 'core show channels' 2>/dev/null || echo 'Нет активных звонков'",
    "env":      "grep -v 'KEY\\|TOKEN\\|PASS\\|SECRET' /opt/alina/.env || echo 'файл не найден'",
}


class RunRequest(BaseModel):
    command: str   # ключ из SAFE_COMMANDS или raw (только для admin)
    raw: bool = False


@app.post("/run")
async def run_command(req: RunRequest, x_secret: str = Header(None)):
    if x_secret != SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")

    if req.raw:
        # Произвольная команда — только для доверенных запросов
        cmd = req.command
    else:
        cmd = SAFE_COMMANDS.get(req.command)
        if not cmd:
            return {"output": f"Неизвестная команда. Доступные: {', '.join(SAFE_COMMANDS)}"}

    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=30
        )
        output = (result.stdout + result.stderr).strip()
        return {"output": output or "Команда выполнена (нет вывода)", "rc": result.returncode}
    except subprocess.TimeoutExpired:
        return {"output": "Таймаут выполнения (30 сек)", "rc": -1}
    except Exception as e:
        return {"output": f"Ошибка: {e}", "rc": -1}


@app.get("/health")
async def health():
    return {"status": "ok"}
