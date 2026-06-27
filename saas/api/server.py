"""
Единый сервер: лендинг + SaaS API + голосовой агент + автодозвон.
Запуск: uvicorn saas.api.server:app --host 0.0.0.0 --port 8080
"""

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, FileResponse
from pathlib import Path

from saas.api.main import app as saas_app
from voice_agent import app as voice_app
from autocall import router as autocall_router

app = FastAPI(title="AuraAI Platform")

app.mount("/api/v1", saas_app)
app.mount("/voice", voice_app)
app.include_router(autocall_router)   # /autocall/event, /autocall/audio

TEMPLATES = Path(__file__).parent.parent / "templates"

@app.get("/", response_class=HTMLResponse)
async def landing():
    return FileResponse(TEMPLATES / "index.html")

@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}
