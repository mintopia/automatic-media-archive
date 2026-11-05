"""Routes: the Now page, sign-in, and the SSE stream. Job pages are in `jobs_pages`."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse

from ama.web import FRAGMENTS, TEMPLATES, auth, fragments_for, render_fragment, view_context
from ama.web.now_output import StepOutput, tail

router = APIRouter()

KEEPALIVE_SECONDS = 15


def _services(request: Request):
    return request.app.state.services


@router.get("/", response_class=HTMLResponse)
def now(request: Request) -> Response:
    ctx = view_context(_services(request)) | {"current": "/"}
    return TEMPLATES.TemplateResponse(request, "now.html", ctx)


@router.get("/now/output", response_class=HTMLResponse)
def now_output(request: Request, steps: str = "") -> Response:
    """What Now polls on each `logs` SSE event while a "Show output" is open: the newest
    lines of each running Step in `steps` (comma-separated ids), swapped in out of band."""
    services = _services(request)
    ids = [int(s) for s in steps.split(",") if s.strip().isdigit()]
    outs = [StepOutput(i, "", tail(services, i)) for i in ids if services.runs.running(i)]
    return TEMPLATES.TemplateResponse(request, "partials/now_output_live.html", {"outs": outs})


@router.get("/makemkv", response_class=HTMLResponse)
def makemkv(request: Request) -> Response:
    ctx = view_context(_services(request)) | {"current": "/"}
    return TEMPLATES.TemplateResponse(request, "makemkv.html", ctx)


@router.post("/makemkv/check")
async def makemkv_check(request: Request) -> Response:
    await _services(request).tools.check_makemkv()
    return RedirectResponse("/makemkv", status_code=303)


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


@router.post("/logout")
def logout() -> Response:
    r = RedirectResponse("/login", status_code=303)
    r.delete_cookie(auth.COOKIE)
    return r


def _back(request: Request) -> Response:
    """Back to the page the menu was used on (its path only: never off-site)."""
    path = urlsplit(request.headers.get("referer", "")).path
    return RedirectResponse(path if path.startswith("/") and not path.startswith("//") else "/",
                            status_code=303)


@router.post("/pause")
async def pause(request: Request) -> Response:
    _services(request).pause.set(True)
    return _back(request)


@router.get("/control")
def control(request: Request) -> Response:
    """What the supervisor's tray shows (`ama.tray`)."""
    return JSONResponse({"paused": _services(request).pause.paused},
                        headers={"Cache-Control": "no-store"})


@router.post("/control/quit")
def control_quit(request: Request) -> Response:
    """The tray's Quit. Only the supervisor (it holds the token) may stop AMA for good."""
    token = request.app.state.control_token
    if not (token and auth.is_control(request, token)):
        return Response(status_code=403)
    _services(request).restart.stop()
    return Response(status_code=204)


@router.post("/resume")
async def resume(request: Request) -> Response:
    _services(request).pause.set(False)
    return _back(request)


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
