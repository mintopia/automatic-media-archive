"""Optional shared password.

`web.password` empty = no auth. Set = every route except /login, /static and /boot
needs the session cookie: HMAC(secret, password), where the secret lives in
SQLite. Sign-ins survive restarts; changing the password signs everyone out.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, RedirectResponse, Response

if TYPE_CHECKING:
    from ama.app import Services
    from ama.db import Database

COOKIE = "ama_session"
CONTROL_HEADER = "X-AMA-Control"  # the supervisor's tray (ama.tray)
OPEN_PREFIXES = ("/login", "/static/")  # open without signing in, with what's under them
OPEN_EXACT = frozenset({"/boot"})  # open as exactly this path only
COOKIE_OPTIONS = {"httponly": True, "samesite": "lax", "max_age": 365 * 24 * 3600}  # a year


def signed_in_token(db: Database, password: str) -> str:
    """The session cookie's value for `password`, keyed by the secret in `db` (made once)."""
    secret = db.get_value("session_secret")
    if secret is None:
        secret = secrets.token_hex(32)
        db.set_value("session_secret", secret)
    return hmac.new(secret.encode(), password.encode(), hashlib.sha256).hexdigest()


def session_token(services: Services) -> str:
    return signed_in_token(services.db, services.config.web.password)


def sign_in(response: Response, token: str) -> None:
    """Make the browser that gets `response` signed in."""
    response.set_cookie(COOKIE, token, **COOKIE_OPTIONS)


def password_matches(services: Services, attempt: str) -> bool:
    return hmac.compare_digest(attempt.encode(), services.config.web.password.encode())


def auth_required(services: Services) -> bool:
    return bool(services.config.web.password)


def is_control(request: Request, control_token: str) -> bool:
    """The request comes from the supervisor's tray (`ama.tray`)."""
    return hmac.compare_digest(request.headers.get(CONTROL_HEADER, "").encode(),
                               control_token.encode())


def install(app: FastAPI, services: Services, control_token: str = "") -> None:
    if not auth_required(services):
        return
    token = session_token(services)

    @app.middleware("http")
    async def require_session(request: Request, call_next) -> Response:
        path = request.url.path
        if path in OPEN_EXACT or path.startswith(OPEN_PREFIXES) or hmac.compare_digest(
            request.cookies.get(COOKIE, ""), token
        ) or (control_token and is_control(request, control_token)):
            return await call_next(request)
        if path == "/events":
            return PlainTextResponse("Sign in first", status_code=401)
        return RedirectResponse("/login", status_code=303)
