"""Routes: the Now page, Disc pages, sign-in, and the SSE stream."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import (
    HTMLResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)

from ama.discs import DiscStatus, FailureKind
from ama.web import FRAGMENTS, TEMPLATES, auth, render_fragment, view_context

router = APIRouter()

KEEPALIVE_SECONDS = 15


def _services(request: Request):
    return request.app.state.services


@router.get("/", response_class=HTMLResponse)
def now(request: Request) -> Response:
    ctx = view_context(_services(request)) | {"current": "/"}
    return TEMPLATES.TemplateResponse(request, "now.html", ctx)


@router.get("/disc", response_class=HTMLResponse)
def disc_in_drive(request: Request) -> Response:
    """The Disc being ripped, live. Once it's done, its record page."""
    services = _services(request)
    ripper = services.video_rip
    if ripper.active is None:
        return RedirectResponse(f"/discs/{ripper.disc.id}" if ripper.disc else "/", status_code=303)
    ctx = view_context(services) | {"current": "/", "live": True}
    return TEMPLATES.TemplateResponse(request, "disc.html", ctx)


def _disc_or_404(services, disc_id: int):
    disc = services.discs.get(disc_id)
    if disc is None:
        raise HTTPException(404, "No such Disc")
    return disc


@router.get("/discs/{disc_id}", response_class=HTMLResponse)
def disc_page(request: Request, disc_id: int) -> Response:
    services = _services(request)
    disc = _disc_or_404(services, disc_id)
    active = services.video_rip.active
    if active is not None and active.id == disc_id:
        return RedirectResponse("/disc", status_code=303)
    ctx = view_context(services) | {"current": "/", "disc": disc}
    if disc.status == DiscStatus.FAILED:
        ctx["log_lines"] = services.discs.log_lines(disc_id)
        licence = disc.failure is not None and disc.failure.kind == FailureKind.LICENCE
        ctx["log_open"] = not licence
        return TEMPLATES.TemplateResponse(
            request, "disc_licence.html" if licence else "disc_failed.html", ctx)
    ctx |= {"rip_disc": disc, "rip_progress": None, "live": False}
    return TEMPLATES.TemplateResponse(request, "disc.html", ctx)


@router.get("/discs/{disc_id}/log", response_class=PlainTextResponse)
def disc_log(request: Request, disc_id: int) -> str:
    services = _services(request)
    _disc_or_404(services, disc_id)
    return "\n".join(map(str, services.discs.log_lines(disc_id))) + "\n"


@router.post("/discs/{disc_id}/dismiss")
def dismiss_disc(request: Request, disc_id: int) -> Response:
    services = _services(request)
    _disc_or_404(services, disc_id)
    services.discs.dismiss(disc_id)
    services.bus.publish("drive")
    return RedirectResponse("/", status_code=303)


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
            for topic in FRAGMENTS:
                yield _sse(topic, render_fragment(topic, services))
            while not await request.is_disconnected():
                try:
                    topic = await asyncio.wait_for(q.get(), KEEPALIVE_SECONDS)
                except TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if topic in FRAGMENTS:
                    yield _sse(topic, render_fragment(topic, services))

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})
