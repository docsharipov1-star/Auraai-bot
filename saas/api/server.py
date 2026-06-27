"""
Единый сервер: лендинг + SaaS API + голосовой агент.
Запуск: uvicorn saas.api.server:app --host 0.0.0.0 --port 8080
"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pathlib import Path
import os

# Импортируем оба приложения
from saas.api.main import app as saas_app
from voice_agent import app as voice_app

app = FastAPI(title="AuraAI Platform")

# Подключаем SaaS API
app.mount("/api/v1", saas_app)

# Подключаем голосовой агент
app.mount("/voice", voice_app)

# Статика
TEMPLATES = Path(__file__).parent.parent / "templates"

@app.get("/", response_class=HTMLResponse)
async def landing():
    return FileResponse(TEMPLATES / "index.html")

@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}
