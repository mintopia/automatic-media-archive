"""Routes for one Disc: its Rip (live or finished), or why it failed."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from ama.discs import DiscStatus
from ama.drive import DiscType
from ama.web import TEMPLATES, view_context

router = APIRouter()


@router.get("/discs/{disc_id}", response_class=HTMLResponse)
def disc_page(request: Request, disc_id: int) -> Response:
    services = request.app.state.services
    rec = services.discs.get(disc_id)
    if rec is None:
        raise HTTPException(404)
    ctx = view_context(services) | {"current": "/", "record": rec}
    if rec.status == DiscStatus.FAILED:
        tracks = services.cd.disc(disc_id).tracks if rec.disc_type == DiscType.CD else []
        ctx |= {"log": services.discs.log_lines(disc_id), "track_count": len(tracks)}
        return TEMPLATES.TemplateResponse(request, "disc_failed.html", ctx)
    if rec.disc_type != DiscType.CD:
        raise HTTPException(404)
    cd = services.cd.current
    live = cd is not None and cd.disc_id == disc_id
    view = cd if live else services.cd.disc(disc_id)
    ctx |= {"live": live, "view": view, "title": rec.label or "Unknown CD"}
    return TEMPLATES.TemplateResponse(request, "disc_cd.html", ctx)


@router.post("/discs/{disc_id}/dismiss")
def dismiss(request: Request, disc_id: int, next: Annotated[str, Form()] = "") -> Response:
    """Dismiss a failed Disc from Now. "Try again" also dismisses: re-inserting the Disc Rips it."""
    services = request.app.state.services
    rec = services.discs.get(disc_id)
    if rec is None:
        raise HTTPException(404)
    if rec.status == DiscStatus.FAILED:
        services.discs.dismiss(disc_id)
        services.bus.publish("rip")
    return RedirectResponse("/", status_code=303)
