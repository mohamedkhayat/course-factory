"""LAN access for the tablet: pairing by a one-time code started on the host, then a revocable device token.
Ported from Atlas. The host itself (loopback) needs no pairing; the models and data stay on the host."""

import hashlib
import ipaddress
import json
import secrets
import time
import uuid
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

CODE_TTL = 10 * 60
MAX_FAILED_CLAIMS = 5  # per open code window: then every open code is revoked (a six-digit code is guessable)
COOKIE = "cf_session"
LOOPBACK = {"127.0.0.1", "::1"}
OPEN_PATHS = {"/api/pairing/claim"}

PAIRING_SCHEMA = """
CREATE TABLE IF NOT EXISTS pairing_codes (
  id TEXT PRIMARY KEY, code_hash TEXT NOT NULL, created_at REAL NOT NULL, expires_at REAL NOT NULL,
  claimed_at REAL, revoked INTEGER NOT NULL DEFAULT 0, failed INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS paired_clients (
  id TEXT PRIMARY KEY, label TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE, created_at REAL NOT NULL,
  last_seen_at REAL NOT NULL, revoked_at REAL
);
"""


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class Claim(BaseModel):
    code: str
    label: str = "Tablet"


def host_ok(host: str) -> bool:
    """Only IP literals and localhost: a DNS-rebinding page arrives with its own domain name."""
    name = urlsplit(f"//{host}").hostname or ""
    if name == "localhost":
        return True
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        return False


class PairingGuard:
    """ASGI middleware for HTTP and WebSocket: loopback is the host; anyone else needs a paired device token."""

    def __init__(self, app, db):
        self.app, self.db = app, db

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
        origin = headers.get("origin")
        if not host_ok(headers.get("host", "")) or (origin and urlsplit(origin).netloc != headers.get("host")):
            return await self.deny(scope, send, 403, "cross-site or unknown host")
        client = (scope.get("client") or ("", 0))[0]
        scope.setdefault("state", {})
        if client in LOOPBACK:
            scope["state"]["device"] = {"id": "host", "label": "Host"}
        elif scope["path"].startswith("/api/") and scope["path"] not in OPEN_PATHS:
            device = authenticate(self.db, token_of(headers))
            if device is None:
                return await self.deny(scope, send, 401, "pair this device first")
            scope["state"]["device"] = device
        return await self.app(scope, receive, send)

    async def deny(self, scope, send, status: int, detail: str):
        if scope["type"] == "websocket":
            return await send({"type": "websocket.close", "code": 4000 + status})
        body = json.dumps({"detail": detail}).encode()
        await send({"type": "http.response.start", "status": status, "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": body})


def token_of(headers: dict) -> str | None:
    auth = headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    for item in headers.get("cookie", "").split(";"):
        k, _, v = item.strip().partition("=")
        if k == COOKIE:
            return v
    return None


def authenticate(db, token: str | None) -> dict | None:
    if not token:
        return None
    row = db.execute("SELECT id, label FROM paired_clients WHERE token_hash=? AND revoked_at IS NULL", (_hash(token),)).fetchone()
    if row is None:
        return None
    db.execute("UPDATE paired_clients SET last_seen_at=? WHERE id=?", (time.time(), row["id"]))
    return {"id": row["id"], "label": row["label"]}


def router(db) -> APIRouter:
    db.executescript(PAIRING_SCHEMA)
    r = APIRouter()

    def host_only(request: Request):
        if request.state.device["id"] != "host":
            raise HTTPException(403, "only the host can do this")

    @r.post("/api/pairing/start")
    def start(request: Request):
        """A fresh six-digit code, shown on the host and typed on the tablet. Starting one revokes older open codes."""
        host_only(request)
        now = time.time()
        code = f"{secrets.randbelow(1_000_000):06d}"
        db.execute("UPDATE pairing_codes SET revoked=1 WHERE claimed_at IS NULL")
        db.execute("INSERT INTO pairing_codes (id, code_hash, created_at, expires_at) VALUES (?,?,?,?)",
                   (uuid.uuid4().hex, _hash(code), now, now + CODE_TTL))
        return {"code": code, "expires_at": now + CODE_TTL}

    @r.post("/api/pairing/claim")
    def claim(body: Claim, response: Response):
        now = time.time()
        code = body.code.strip()
        row = db.execute("SELECT id FROM pairing_codes WHERE code_hash=? AND claimed_at IS NULL AND revoked=0 AND expires_at>?",
                         (_hash(code), now)).fetchone() if len(code) == 6 and code.isdigit() else None
        if row is None:
            db.execute("UPDATE pairing_codes SET failed=failed+1 WHERE claimed_at IS NULL AND revoked=0")
            db.execute("UPDATE pairing_codes SET revoked=1 WHERE claimed_at IS NULL AND failed>=?", (MAX_FAILED_CLAIMS,))
            raise HTTPException(400, "the code is wrong or expired")
        token = secrets.token_urlsafe(32)
        client_id = uuid.uuid4().hex
        label = body.label.strip()[:100] or "Tablet"
        db.execute("UPDATE pairing_codes SET claimed_at=? WHERE id=?", (now, row["id"]))
        db.execute("INSERT INTO paired_clients (id, label, token_hash, created_at, last_seen_at) VALUES (?,?,?,?,?)",
                   (client_id, label, _hash(token), now, now))
        response.set_cookie(COOKIE, token, httponly=True, samesite="strict", max_age=10 * 365 * 86400)
        return {"client_id": client_id, "label": label}

    @r.get("/api/pairing/me")
    def me(request: Request):
        return request.state.device

    @r.get("/api/pairing/clients")
    def clients(request: Request):
        host_only(request)
        return [dict(x) for x in db.execute("SELECT id, label, created_at, last_seen_at, revoked_at FROM paired_clients ORDER BY created_at DESC")]

    @r.post("/api/pairing/clients/{client_id}/revoke")
    def revoke(client_id: str, request: Request):
        if request.state.device["id"] not in ("host", client_id):
            raise HTTPException(403, "only the host can revoke another device")
        if not db.execute("UPDATE paired_clients SET revoked_at=? WHERE id=? AND revoked_at IS NULL", (time.time(), client_id)).rowcount:
            raise HTTPException(404, "no such paired device")
        return {"ok": True}

    return r
