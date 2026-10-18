"""
Единый сервер: лендинг + SaaS API + голосовой агент + автодозвон.
Запуск: uvicorn saas.api.server:app --host 0.0.0.0 --port 8080
"""

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, FileResponse
from fastapi import Request
from fastapi.responses import JSONResponse
from pathlib import Path

from saas.api.main import app as saas_app
from voice_agent import app as voice_app
from autocall import router as autocall_router
from admin_agent import router as admin_router
from call_queue import router as alina_router
try:
    from psych_agent import get_session, reset_session
    _psych_ok = True
except ImportError:
    _psych_ok = False
    def get_session(uid): return None
    def reset_session(uid): pass

app = FastAPI(title="AuraAI Platform")

app.mount("/api/v1", saas_app)
app.mount("/voice", voice_app)
app.include_router(autocall_router)   # /autocall/event, /autocall/audio
app.include_router(admin_router)      # /admin/call/start|audio|end|test
app.include_router(alina_router)      # /alina/event, /alina/inbound, /alina/audio

TEMPLATES = Path(__file__).parent.parent / "templates"

@app.get("/", response_class=HTMLResponse)
async def landing():
    return FileResponse(TEMPLATES / "index.html")

@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}

# ── Психолог-агент Sage (веб-чат) ────────────────────────────────────────────

@app.post("/api/psych/chat")
async def psych_chat(request: Request):
    if not _psych_ok:
        return JSONResponse({"reply": "Агент временно недоступен. Попробуйте позже."})
    body = await request.json()
    session_id = body.get("session_id", "web_anon")
    message = body.get("message", "").strip()
    if not message:
        return JSONResponse({"error": "empty message"}, status_code=400)
    session = get_session(session_id)
    reply = await session.reply(message)
    return {"reply": reply, "session_id": session_id}

@app.post("/api/psych/start")
async def psych_start(request: Request):
    body = await request.json()
    session_id = body.get("session_id", "web_anon")
    greeting = "Привет. Я Аура — твой AI-помощник по эмоциональному состоянию. Здесь безопасно, всё остаётся между нами. Что тебя беспокоит сегодня?"
    if _psych_ok:
        reset_session(session_id)
        session = get_session(session_id)
        greeting = session.greeting()
    return {"greeting": greeting, "session_id": session_id}

@app.get("/psych", response_class=HTMLResponse)
async def psych_page():
    return FileResponse(TEMPLATES / "psych.html")

@app.post("/api/psych/tts")
async def psych_tts(request: Request):
    import os
    from fastapi.responses import Response as FastResponse
    body = await request.json()
    text = body.get("text", "").strip()[:600]
    if not text:
        return JSONResponse({"error": "empty"}, status_code=400)
    try:
        import openai
        client = openai.AsyncOpenAI(api_key=os.getenv("OPENAI_KEY", ""))
        response = await client.audio.speech.create(
            model="tts-1", voice="nova", input=text
        )
        return FastResponse(content=response.content, media_type="audio/mpeg")
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
