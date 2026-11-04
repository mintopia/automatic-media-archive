"""History: every filed Disc, newest first, and the cached cover art and posters."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response

from ama.web import TEMPLATES, filed_discs, view_context

router = APIRouter()

LIMIT = 500  # rows on the History page


@router.get("/history", response_class=HTMLResponse)
def history(request: Request) -> Response:
    services = request.app.state.services
    ctx = view_context(services) | {"current": "/history",
                                    "history": filed_discs(services, LIMIT)}
    return TEMPLATES.TemplateResponse(request, "history.html", ctx)


@router.get("/covers/{name}")
def cover(request: Request, name: str) -> FileResponse:
    path = request.app.state.services.covers.path(name)
    if path is None:
        raise HTTPException(404, "No such cover")
    return FileResponse(path, headers={"Cache-Control": "max-age=86400"})
