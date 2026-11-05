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

COOKIE = "ama_session"
CONTROL_HEADER = "X-AMA-Control"  # the supervisor's tray (ama.tray)
OPEN_PATHS = ("/login", "/static/", "/boot")


def _secret(services: Services) -> str:
    secret = services.db.get_value("session_secret")
    if secret is None:
        secret = secrets.token_hex(32)
        services.db.set_value("session_secret", secret)
    return secret


def session_token(services: Services) -> str:
    password = services.config.web.password
    return hmac.new(_secret(services).encode(), password.encode(), hashlib.sha256).hexdigest()


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
        if path.startswith(OPEN_PATHS) or hmac.compare_digest(
            request.cookies.get(COOKIE, ""), token
        ) or (control_token and is_control(request, control_token)):
            return await call_next(request)
        if path == "/events":
            return PlainTextResponse("Sign in first", status_code=401)
        return RedirectResponse("/login", status_code=303)
