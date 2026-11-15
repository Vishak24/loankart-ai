"""Authentication, authorisation, rate limiting and request hardening. See SECURITY.md for the model and its limits.

Two kinds of session, both HMAC-signed, expiring, HttpOnly cookies (a cookie, not a bearer header, because PDF links
open as plain browser navigations):

* advisor  - granted by the advisor passcode; may use every case and the advisor / demo-control routes.
* borrower - granted when a borrower profile is created (or the shared synthetic demo case is opened); may use only the
             borrowers it was granted. Case, borrower and document IDs are never treated as secrets.

Nothing reads a client-supplied role header any more.
"""

import base64
import hashlib
import hmac
import json
import sqlite3
import threading
import time
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from . import db
from .config import Settings
from .errors import Forbidden, NotFound, Unauthorized

ADVISOR_COOKIE = "lk_adv"
BORROWER_COOKIE = "lk_bor"
MAX_BORROWER_GRANTS = 25
MAX_JSON_BODY = 1024 * 1024
UPLOAD_OVERHEAD = 256 * 1024              # multipart framing on top of the file itself
UNAUTHENTICATED_BODY_LIMIT = 100 * 1024   # bigger bodies are refused before parsing unless a session exists


# ---------------------------------------------------------------------------------------------- shared dependencies

def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_conn(request: Request) -> Iterator[sqlite3.Connection]:
    conn = db.connect(request.app.state.settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------------------------------------- signed tokens

def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign(secret: str, payload: dict[str, Any], hours: int) -> str:
    body = _b64(json.dumps({**payload, "exp": int(time.time() + hours * 3600)}, separators=(",", ":")).encode())
    mac = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64(mac)}"


def unsign(secret: str, token: str | None) -> dict[str, Any] | None:
    """The payload if the signature is valid and the token has not expired; otherwise None."""
    try:
        body, _, mac = (token or "").partition(".")
        good = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
        if not body or not hmac.compare_digest(good, _unb64(mac)):
            return None
        payload = json.loads(_unb64(body))
        return payload if isinstance(payload, dict) and payload.get("exp", 0) > time.time() else None
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------------------------- sessions

@dataclass(frozen=True)
class Session:
    advisor: bool = False
    borrowers: tuple[str, ...] = ()

    @property
    def authenticated(self) -> bool:
        return self.advisor or bool(self.borrowers)


def session_of(request: Request) -> Session:
    cached = getattr(request.state, "session", None)
    if cached is not None:
        return cached
    key = request.app.state.settings.secret_key
    adv = unsign(key, request.cookies.get(ADVISOR_COOKIE))
    bor = unsign(key, request.cookies.get(BORROWER_COOKIE))
    ids = bor.get("b") if bor else None
    found = Session(advisor=bool(adv and adv.get("r") == "advisor"),
                    borrowers=tuple(i for i in ids if isinstance(i, str))[-MAX_BORROWER_GRANTS:] if isinstance(ids, list) else ())
    request.state.session = found
    return found


def _set_cookie(response: Response, settings: Settings, name: str, token: str, hours: int) -> None:
    response.set_cookie(name, token, max_age=hours * 3600, httponly=True, samesite="lax", path="/",  # gitleaks:allow (code, not a credential)
                        secure=settings.is_production)


def grant_borrower(request: Request, response: Response, borrower_id: str) -> None:
    """Let this browser use one borrower profile and its case. Called only where a profile is created or the shared
    synthetic demo case is opened."""
    s = request.app.state.settings
    kept = [b for b in session_of(request).borrowers if b != borrower_id] + [borrower_id]
    token = sign(s.secret_key, {"b": kept[-MAX_BORROWER_GRANTS:]}, s.borrower_session_hours)
    _set_cookie(response, s, BORROWER_COOKIE, token, s.borrower_session_hours)


def grant_advisor(request: Request, response: Response) -> None:
    s = request.app.state.settings
    _set_cookie(response, s, ADVISOR_COOKIE, sign(s.secret_key, {"r": "advisor"}, s.advisor_session_hours), s.advisor_session_hours)


def clear_sessions(response: Response) -> None:
    for name in (ADVISOR_COOKIE, BORROWER_COOKIE):
        response.delete_cookie(name, path="/")


def passcode_matches(settings: Settings, attempt: str) -> bool:
    return bool(settings.advisor_password) and hmac.compare_digest(attempt.encode(), settings.advisor_password.encode())


# ---------------------------------------------------------------------------------------------- access guards

def require_session(request: Request) -> Session:
    s = session_of(request)
    if not s.authenticated:
        raise Unauthorized("Your session has expired or has not started. Open the case again from the home page.")
    return s


def require_advisor(request: Request) -> str:
    if not session_of(request).advisor:
        raise Unauthorized("Advisor sign-in required. Reload the page to sign in.")
    return "advisor"


def require_demo_admin(request: Request) -> str:
    """Reset, scenario loading, logs and similar. Absent (404) in production unless explicitly enabled; advisors only."""
    if not request.app.state.settings.demo_tools:
        raise NotFound("Not found")
    return require_advisor(request)


def _owns(s: Session, borrower_id: str | None) -> bool:
    return s.advisor or (borrower_id is not None and borrower_id in s.borrowers)


def borrower_access(request: Request, borrower_id: str) -> None:
    s = require_session(request)
    if not _owns(s, borrower_id):
        raise Forbidden("This profile is not open in your session.")


def case_access(request: Request, case_id: str, conn: Annotated[sqlite3.Connection, Depends(get_conn)]) -> None:
    s = require_session(request)
    if s.advisor:
        return
    case = db.get_case(conn, case_id)
    if case is None or not _owns(s, case["borrower_id"]):     # same answer for "missing" and "not yours": no probing
        raise Forbidden("This case is not open in your session. Start again from the home page.")


def document_access(request: Request, doc_id: str, conn: Annotated[sqlite3.Connection, Depends(get_conn)]) -> None:
    s = require_session(request)
    if s.advisor:
        return
    doc = db.get_document(conn, doc_id)
    case = db.get_case(conn, doc["case_id"]) if doc else None
    if case is None or not _owns(s, case["borrower_id"]):
        raise Forbidden("This document is not available in your session.")


# ---------------------------------------------------------------------------------------------- rate limiting

class RateLimiter:
    """Sliding window, in memory, per process. Enough for one server; use a shared store behind several."""

    def __init__(self) -> None:
        self._hits: dict[tuple[str, str], deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, bucket: str, key: str, limit: int, window: float) -> int | None:
        """Record a hit. Returns None if allowed, else the seconds to wait."""
        if limit <= 0:
            return None
        now = time.monotonic()
        with self._lock:
            hits = self._hits.setdefault((bucket, key), deque())
            while hits and now - hits[0] >= window:
                hits.popleft()
            if len(hits) >= limit:
                return max(1, int(window - (now - hits[0])) + 1)
            hits.append(now)
            if len(self._hits) > 20_000:                   # forget idle clients
                for k in [k for k, v in self._hits.items() if not v or now - v[-1] >= window]:
                    del self._hits[k]
            return None


def client_ip(request: Request) -> str:
    if request.app.state.settings.trust_proxy:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[-1].strip()      # the address our own proxy appended, not a client claim
    return request.client.host if request.client else "unknown"


def _too_many(wait: int) -> HTTPException:
    return HTTPException(429, "Too many requests. Please wait a moment and try again.", headers={"Retry-After": str(wait)})


def _limited(bucket: str, attr: str) -> Any:
    def dependency(request: Request) -> None:
        wait = request.app.state.limiter.check(bucket, client_ip(request), getattr(request.app.state.settings, attr), 60)
        if wait:
            raise _too_many(wait)
    return Depends(dependency)


login_limit = _limited("login", "rate_login")
upload_limit = _limited("upload", "rate_upload")
create_limit = _limited("create", "rate_create")


def _ai_limit(request: Request) -> None:
    """Routes that can spend provider credits: a per-client rate and a whole-server daily ceiling."""
    s, limiter = request.app.state.settings, request.app.state.limiter
    wait = limiter.check("ai", client_ip(request), s.rate_ai, 60) or limiter.check("ai-day", "*", s.rate_ai_daily, 86400)
    if wait:
        raise _too_many(wait)


ai_limit = Depends(_ai_limit)


# ---------------------------------------------------------------------------------------------- HTTP middleware

def _upload_limit_for(request: Request) -> int:
    from .environment import MAX_UPLOAD_BYTES
    path = request.url.path
    if request.method == "POST" and path.endswith("/documents") and path.startswith("/api/cases/"):
        return MAX_UPLOAD_BYTES + UPLOAD_OVERHEAD
    if path == "/api/ai/transcribe":
        return 8 * 1024 * 1024 + UPLOAD_OVERHEAD
    return MAX_JSON_BODY


def _refuse(status: int, detail: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail}, headers=headers)


async def http_guard(request: Request, call_next: Any) -> Response:
    """Per-request checks that must run before a body is parsed, and security headers on every response."""
    s: Settings = request.app.state.settings
    if request.url.path.startswith("/api"):
        wait = request.app.state.limiter.check("default", client_ip(request), s.rate_default, 60)
        if wait:
            return _refuse(429, "Too many requests. Please wait a moment and try again.", {"Retry-After": str(wait)})
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            origin = request.headers.get("origin")        # CSRF: browsers always send it on cross-site writes
            if origin and origin not in s.cors_origins and origin.split("://", 1)[-1] != request.headers.get("host"):
                return _refuse(403, "Cross-site request refused. If this is your own front end, add its address to LOANKART_CORS_ORIGINS.")
            length = request.headers.get("content-length")
            if length is None and request.headers.get("transfer-encoding"):
                return _refuse(411, "A Content-Length header is required.")     # chunked bodies would dodge the size cap
            if length is not None:
                if not length.isdigit() or int(length) > _upload_limit_for(request):
                    return _refuse(413, "The request is too large.")
                if int(length) > UNAUTHENTICATED_BODY_LIMIT and not session_of(request).authenticated:
                    return _refuse(401, "Your session has expired or has not started.")
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if request.url.path.startswith("/api"):
        response.headers.setdefault("Cache-Control", "no-store")
        if response.headers.get("content-type", "").startswith("application/json"):
            response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
    if s.is_production:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response
