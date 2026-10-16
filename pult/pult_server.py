"""
Пульт клиники «Аура» — автономный сервер для VPS.

  • Вход по почте: код из письма (Mail.ru SMTP). Без Google и claude.ai.
  • Владелец (OWNER_EMAIL) видит всё и меняет настройки; администраторы —
    почты из «Настройки → Доступ».
  • Данные — SQLite в /opt/pult/data, автокопия каждый день в /opt/pult/backups.

Запуск: uvicorn pult_server:app --host 0.0.0.0 --port 8600
.env (см. setup_pult.sh):
  OWNER_EMAIL=you@mail.ru            # можно несколько через запятую
  SMTP_HOST=smtp.mail.ru
  SMTP_PORT=465
  SMTP_USER=pult-aura@mail.ru        # ящик, с которого уходят коды
  SMTP_PASS=пароль-для-внешнего-приложения
  PULT_SECRET=случайная-строка
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import smtplib
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import date, datetime
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse

log = logging.getLogger("pult")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

HERE = Path(__file__).parent
DATA_DIR = Path(os.getenv("PULT_DATA", HERE / "data"))
BACKUP_DIR = Path(os.getenv("PULT_BACKUPS", HERE / "backups"))
DB_PATH = DATA_DIR / "pult.db"
STATIC = HERE / "static" / "index.html"

OWNER_EMAILS = {e.strip().lower() for e in os.getenv("OWNER_EMAIL", "").split(",") if e.strip()}
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.mail.ru")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SECRET = os.getenv("PULT_SECRET", "") or secrets.token_hex(32)
SESSION_DAYS = 30
CODE_TTL = 600          # код действует 10 минут
CODE_COOLDOWN = 60      # новый код не чаще раза в минуту
CODE_ATTEMPTS = 5
BACKUP_KEEP = 30

COLLECTIONS = {"config", "patients", "plans", "day"}
PATH_RE = re.compile(r"^([a-z]+)/([A-Za-z0-9_\-.:]{1,120})$")
FIELD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,40}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
OPS = {"==": "=", ">=": ">=", "<=": "<=", ">": ">", "<": "<"}

DATA_DIR.mkdir(parents=True, exist_ok=True)
BACKUP_DIR.mkdir(parents=True, exist_ok=True)
_lock = threading.Lock()


# ── база ──────────────────────────────────────────────────────────────────────

def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


@contextmanager
def _db():
    c = _conn()
    try:
        yield c
    finally:
        c.close()


def init_db():
    with _db() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS docs (
                path TEXT PRIMARY KEY, coll TEXT NOT NULL, data TEXT NOT NULL, updated TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS docs_coll ON docs(coll);
            CREATE TABLE IF NOT EXISTS changes (seq INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS codes (
                email TEXT PRIMARY KEY, hash TEXT NOT NULL, expires REAL NOT NULL, sent REAL NOT NULL, attempts INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY, email TEXT NOT NULL, expires REAL NOT NULL);
        """)


def _deep_merge(a: dict, b: dict) -> dict:
    out = dict(a)
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _check_path(path: str) -> tuple[str, str]:
    m = PATH_RE.match(path or "")
    if not m or m.group(1) not in COLLECTIONS:
        raise HTTPException(400, "bad path")
    return m.group(1), m.group(2)


def _write(c: sqlite3.Connection, path: str, coll: str, data: dict):
    body = json.dumps(data, ensure_ascii=False)
    if len(body) > 512_000:
        raise HTTPException(413, "document too large")
    c.execute("INSERT INTO docs(path, coll, data, updated) VALUES(?,?,?,?) "
              "ON CONFLICT(path) DO UPDATE SET data=excluded.data, updated=excluded.updated",
              (path, coll, body, datetime.utcnow().isoformat()))
    c.execute("INSERT INTO changes(path) VALUES(?)", (path,))


# ── доступ ────────────────────────────────────────────────────────────────────

def _admin_emails() -> set[str]:
    with _db() as c:
        row = c.execute("SELECT data FROM docs WHERE path='config/access'").fetchone()
    if not row:
        return set()
    try:
        return {e.strip().lower() for e in json.loads(row["data"]).get("admins", []) if isinstance(e, str)}
    except Exception:
        return set()


def _role(email: str) -> str | None:
    email = email.lower()
    if email in OWNER_EMAILS:
        return "owner"
    if email in _admin_emails():
        return "admin"
    return None


def _hash(value: str) -> str:
    return hmac.new(SECRET.encode(), value.encode(), hashlib.sha256).hexdigest()


def _session(request: Request) -> dict:
    token = request.cookies.get("pult_session", "")
    if not token:
        raise HTTPException(401, "login required")
    with _db() as c:
        row = c.execute("SELECT email, expires FROM sessions WHERE token=?", (_hash(token),)).fetchone()
    if not row or row["expires"] < time.time():
        raise HTTPException(401, "login required")
    role = _role(row["email"])
    if not role:  # почту убрали из доступа
        raise HTTPException(401, "access revoked")
    return {"email": row["email"], "role": role}


def _can_read(user: dict, path: str) -> bool:
    return path != "config/access" or user["role"] == "owner"


def _can_write(user: dict, coll: str) -> bool:
    return coll != "config" or user["role"] == "owner"


# ── почта ─────────────────────────────────────────────────────────────────────

def _send_code(email: str, code: str):
    if not (SMTP_USER and SMTP_PASS):
        log.warning(f"SMTP не настроен — код для {email}: {code}")
        return
    msg = MIMEText(f"Код для входа в пульт клиники «Аура»: {code}\n\nКод действует 10 минут. "
                   f"Если вы не запрашивали вход — просто удалите это письмо.", "plain", "utf-8")
    msg["Subject"] = f"Код входа: {code}"
    msg["From"] = formataddr(("Пульт клиники Аура", SMTP_USER))
    msg["To"] = email
    if SMTP_PORT == 465:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20) as s:
            s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as s:
            s.starttls()
            s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)


# ── резервные копии ───────────────────────────────────────────────────────────

def dump_all() -> dict:
    with _db() as c:
        rows = c.execute("SELECT path, data FROM docs").fetchall()
    return {"app": "aura-pult", "version": 2, "exportedAt": datetime.utcnow().isoformat() + "Z",
            "docs": {r["path"]: json.loads(r["data"]) for r in rows}}


def daily_backup():
    name = BACKUP_DIR / f"pult-{date.today().isoformat()}.json"
    if name.exists():
        return
    name.write_text(json.dumps(dump_all(), ensure_ascii=False), encoding="utf-8")
    old = sorted(BACKUP_DIR.glob("pult-*.json"))[:-BACKUP_KEEP]
    for f in old:
        f.unlink(missing_ok=True)
    log.info(f"Резервная копия: {name}")


async def _backup_loop():
    while True:
        try:
            await asyncio.to_thread(daily_backup)
        except Exception as e:
            log.error(f"backup: {e}")
        await asyncio.sleep(3600)


# ── приложение ────────────────────────────────────────────────────────────────

app = FastAPI(title="Пульт клиники Аура", docs_url=None, redoc_url=None, openapi_url=None)


@app.on_event("startup")
async def _startup():
    init_db()
    if not OWNER_EMAILS:
        log.warning("OWNER_EMAIL не задан — войти никто не сможет")
    asyncio.create_task(_backup_loop())


@app.get("/")
async def index():
    return FileResponse(STATIC, headers={"Cache-Control": "no-cache"})


@app.get("/health")
async def health():
    return {"ok": True}


@app.post("/api/login/request")
async def login_request(request: Request):
    body = await request.json()
    email = str(body.get("email", "")).strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(400, "Похоже, почта написана с ошибкой.")
    if not _role(email):
        # одинаковый ответ, чтобы нельзя было перебором узнать список почт
        return {"ok": True}
    now = time.time()
    with _db() as c:
        row = c.execute("SELECT sent FROM codes WHERE email=?", (email,)).fetchone()
        if row and now - row["sent"] < CODE_COOLDOWN:
            raise HTTPException(429, "Код уже отправлен. Новый можно запросить через минуту.")
        code = f"{secrets.randbelow(1_000_000):06d}"
        c.execute("INSERT OR REPLACE INTO codes(email, hash, expires, sent, attempts) VALUES(?,?,?,?,0)",
                  (email, _hash(email + ":" + code), now + CODE_TTL, now))
    try:
        await asyncio.to_thread(_send_code, email, code)
    except Exception as e:
        log.error(f"SMTP: {e}")
        raise HTTPException(502, "Не получилось отправить письмо. Проверь настройки почты на сервере.")
    return {"ok": True}


@app.post("/api/login/verify")
async def login_verify(request: Request, response: Response):
    body = await request.json()
    email = str(body.get("email", "")).strip().lower()
    code = re.sub(r"\D", "", str(body.get("code", "")))
    with _db() as c:
        row = c.execute("SELECT hash, expires, attempts FROM codes WHERE email=?", (email,)).fetchone()
        if not row or row["expires"] < time.time() or row["attempts"] >= CODE_ATTEMPTS:
            raise HTTPException(400, "Код устарел. Запроси новый.")
        if not hmac.compare_digest(row["hash"], _hash(email + ":" + code)):
            c.execute("UPDATE codes SET attempts=attempts+1 WHERE email=?", (email,))
            raise HTTPException(400, "Неверный код.")
        c.execute("DELETE FROM codes WHERE email=?", (email,))
        if not _role(email):
            raise HTTPException(403, "Нет доступа.")
        token = secrets.token_urlsafe(32)
        c.execute("INSERT INTO sessions(token, email, expires) VALUES(?,?,?)",
                  (_hash(token), email, time.time() + SESSION_DAYS * 86400))
        c.execute("DELETE FROM sessions WHERE expires < ?", (time.time(),))
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie("pult_session", token, max_age=SESSION_DAYS * 86400, httponly=True,
                        samesite="lax", secure=secure)
    return {"ok": True}


@app.post("/api/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get("pult_session", "")
    if token:
        with _db() as c:
            c.execute("DELETE FROM sessions WHERE token=?", (_hash(token),))
    response.delete_cookie("pult_session")
    return {"ok": True}


@app.get("/api/me")
async def me(request: Request):
    return _session(request)


@app.get("/api/doc")
async def get_doc(path: str, request: Request):
    user = _session(request)
    _check_path(path)
    if not _can_read(user, path):
        return {"data": None}
    with _db() as c:
        row = c.execute("SELECT data FROM docs WHERE path=?", (path,)).fetchone()
    return {"data": json.loads(row["data"]) if row else None}


@app.put("/api/doc")
async def put_doc(request: Request):
    user = _session(request)
    body = await request.json()
    path, data = body.get("path", ""), body.get("data")
    coll, _ = _check_path(path)
    if not isinstance(data, dict):
        raise HTTPException(400, "data must be an object")
    if not _can_write(user, coll):
        raise HTTPException(403, "Только владелец меняет настройки.")
    with _lock, _db() as c:
        _write(c, path, coll, data)
    return {"ok": True}


@app.patch("/api/doc")
async def patch_doc(request: Request):
    user = _session(request)
    body = await request.json()
    path, data = body.get("path", ""), body.get("data")
    coll, _ = _check_path(path)
    if not isinstance(data, dict):
        raise HTTPException(400, "data must be an object")
    if not _can_write(user, coll):
        raise HTTPException(403, "Только владелец меняет настройки.")
    with _lock, _db() as c:
        row = c.execute("SELECT data FROM docs WHERE path=?", (path,)).fetchone()
        cur = json.loads(row["data"]) if row else {}
        _write(c, path, coll, _deep_merge(cur, data))
    return {"ok": True}


@app.delete("/api/doc")
async def delete_doc(path: str, request: Request):
    user = _session(request)
    coll, _ = _check_path(path)
    if not _can_write(user, coll):
        raise HTTPException(403, "Только владелец меняет настройки.")
    with _lock, _db() as c:
        c.execute("DELETE FROM docs WHERE path=?", (path,))
        c.execute("INSERT INTO changes(path) VALUES(?)", (path,))
    return {"ok": True}


@app.post("/api/query")
async def query(request: Request):
    user = _session(request)
    body = await request.json()
    coll = body.get("coll", "")
    if coll not in COLLECTIONS:
        raise HTTPException(400, "bad collection")
    sql, args = "SELECT path, data FROM docs WHERE coll=?", [coll]
    for w in body.get("where") or []:
        if not (isinstance(w, list) and len(w) == 3 and FIELD_RE.match(str(w[0])) and w[1] in OPS):
            raise HTTPException(400, "bad filter")
        sql += f" AND json_extract(data, '$.{w[0]}') {OPS[w[1]]} ?"
        args.append(w[2])
    limit = min(int(body.get("limit") or 5000), 20000)
    with _db() as c:
        rows = c.execute(sql + " LIMIT ?", (*args, limit)).fetchall()
    out = []
    for r in rows:
        if _can_read(user, r["path"]):
            d = json.loads(r["data"])
            d["id"] = r["path"].split("/", 1)[1]
            out.append(d)
    return out


@app.get("/api/changes")
async def changes(since: int, request: Request):
    _session(request)
    with _db() as c:
        top = c.execute("SELECT COALESCE(MAX(seq), 0) AS s FROM changes").fetchone()["s"]
        if since <= 0 or since >= top:
            return {"seq": top, "paths": []}
        rows = c.execute("SELECT DISTINCT path FROM changes WHERE seq > ? LIMIT 501", (since,)).fetchall()
        if since < top - 50_000:
            c.execute("DELETE FROM changes WHERE seq < ?", (top - 50_000,))
    paths = [r["path"] for r in rows]
    return {"seq": top, "paths": paths[:500], "reset": len(paths) > 500}


@app.get("/api/backup")
async def backup(request: Request):
    user = _session(request)
    if user["role"] != "owner":
        raise HTTPException(403, "Только владелец.")
    data = json.dumps(dump_all(), ensure_ascii=False)
    fname = f"aura-pult-{date.today().isoformat()}.json"
    return Response(data, media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@app.post("/api/restore")
async def restore(request: Request):
    user = _session(request)
    if user["role"] != "owner":
        raise HTTPException(403, "Только владелец.")
    body = await request.json()
    if body.get("app") != "aura-pult" or not isinstance(body.get("docs"), dict):
        raise HTTPException(400, "Это не файл резервной копии пульта.")
    n = 0
    with _lock, _db() as c:
        c.execute("BEGIN")
        try:
            for path, data in body["docs"].items():
                m = PATH_RE.match(path)
                if not m or m.group(1) not in COLLECTIONS or not isinstance(data, dict):
                    continue
                _write(c, path, m.group(1), data)
                n += 1
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            raise
    return {"ok": True, "restored": n}


@app.exception_handler(HTTPException)
async def _http_error(request: Request, exc: HTTPException):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)
