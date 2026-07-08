"""
Автономный веб-сервер для AI-психолога Аура.
Деплой на VPS: см. setup_psych_vps.sh
Запуск: uvicorn psych_web:app --host 0.0.0.0 --port 8501
"""

import os
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from psych_agent import get_session, reset_session

app = FastAPI(title="Аура — AI Психолог")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

HERE = Path(__file__).parent
TEMPLATES = HERE / "saas" / "templates"


@app.get("/", response_class=HTMLResponse)
async def index():
    return FileResponse(TEMPLATES / "psych.html")


@app.get("/health")
async def health():
    return {"status": "ok", "agent": "Аура"}


@app.post("/api/psych/chat")
async def chat(request: Request):
    body = await request.json()
    session_id = body.get("session_id", "web_anon")
    message = body.get("message", "").strip()
    if not message:
        return JSONResponse({"error": "empty message"}, status_code=400)
    session = get_session(session_id)
    reply = await session.reply(message)
    return {"reply": reply, "session_id": session_id}


@app.post("/api/psych/start")
async def start(request: Request):
    body = await request.json()
    session_id = body.get("session_id", "web_anon")
    reset_session(session_id)
    session = get_session(session_id)
    return {"greeting": session.greeting(), "session_id": session_id}
