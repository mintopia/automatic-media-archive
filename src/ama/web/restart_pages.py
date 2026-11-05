"""Restart routes: the Settings restart banner's buttons (#37, ADR 0009).

POST /restart restarts at once when nothing Rips or Encodes; otherwise it sends
the page back with an inline confirm (`?restart=confirm`) offering Restart now
(`force`) or Restart when idle. The restarting page polls the open `/boot`
until a server with a new boot id answers, then goes back where it was (at the
new port when the port changed).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from ama.web import TEMPLATES, view_context

if TYPE_CHECKING:
    from ama.app import Services

router = APIRouter()


def _back(back: str) -> str:
    """Only a path on this server: never an open redirect."""
    return back if back.startswith("/") and not back.startswith("//") else "/settings"


@router.post("/restart", response_class=HTMLResponse)
async def restart(request: Request, back: str = Form("/settings"),
                  force: str = Form("")) -> Response:
    services: Services = request.app.state.services
    back = _back(back)
    if not force and services.restart.busy():
        return RedirectResponse(f"{back}?restart=confirm", status_code=303)
    after = back
    settings = services.settings
    if settings is not None and "web.port" in settings.pending():
        after = f"{request.url.scheme}://{request.url.hostname}:{settings.saved.web.port}{back}"
    boot = services.restart.boot
    services.restart.now()
    return TEMPLATES.TemplateResponse(request, "restarting.html", view_context(services) | {
        "current": "/settings", "after": after, "boot": boot,
        "boot_url": after.removesuffix(back) + "/boot"})


@router.post("/restart/when-idle")
async def restart_when_idle(request: Request, back: str = Form("/settings")) -> Response:
    request.app.state.services.restart.when_idle()
    return RedirectResponse(_back(back), status_code=303)


@router.post("/restart/cancel")
async def restart_cancel(request: Request, back: str = Form("/settings")) -> Response:
    request.app.state.services.restart.cancel()
    return RedirectResponse(_back(back), status_code=303)


@router.get("/boot")
def boot(request: Request) -> Response:
    """Which server this is; open and cross-origin so a page on the old port can ask."""
    return JSONResponse({"boot": request.app.state.services.restart.boot},
                        headers={"Access-Control-Allow-Origin": "*",
                                 "Cache-Control": "no-store"})
