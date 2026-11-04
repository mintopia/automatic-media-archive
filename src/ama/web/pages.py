"""Routes: the Now page, sign-in, and the SSE stream."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse

from ama.web import FRAGMENTS, TEMPLATES, auth, fragments_for, render_fragment, view_context

router = APIRouter()

KEEPALIVE_SECONDS = 15


def _services(request: Request):
    return request.app.state.services


@router.get("/", response_class=HTMLResponse)
def now(request: Request) -> Response:
    ctx = view_context(_services(request)) | {"current": "/"}
    return TEMPLATES.TemplateResponse(request, "now.html", ctx)


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request) -> Response:
    if not auth.auth_required(_services(request)):
        return RedirectResponse("/", status_code=303)
    return TEMPLATES.TemplateResponse(request, "login.html", {"error": False})


@router.post("/login", response_class=HTMLResponse)
def login(request: Request, password: Annotated[str, Form()] = "") -> Response:
    services = _services(request)
    if not auth.auth_required(services):
        return RedirectResponse("/", status_code=303)
    if not auth.password_matches(services, password):
        return TEMPLATES.TemplateResponse(request, "login.html", {"error": True}, status_code=401)
    r = RedirectResponse("/", status_code=303)
    r.set_cookie(auth.COOKIE, auth.session_token(services), httponly=True, samesite="lax",
                 max_age=365 * 24 * 3600)
    return r


def _sse(event: str, data: str) -> str:
    lines = "".join(f"data: {ln}\n" for ln in data.splitlines() or [""])
    return f"event: {event}\n{lines}\n"


@router.get("/events")
async def events(request: Request) -> StreamingResponse:
    services = _services(request)

    async def stream() -> AsyncIterator[str]:
        with services.bus.subscribe() as q:
            # Resync everything on (re)connect: the browser may have missed events.
            for name in FRAGMENTS:
                yield _sse(name, render_fragment(name, services))
            while not await request.is_disconnected():
                try:
                    topic = await asyncio.wait_for(q.get(), KEEPALIVE_SECONDS)
                except TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                for name in fragments_for(topic):
                    yield _sse(name, render_fragment(name, services))

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})
