"""History: every filed Disc, newest first, and the cached cover art and posters."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response

from ama.sets import SetKind
from ama.web import TEMPLATES, filed_discs, view_context

router = APIRouter()

LIMIT = 500  # rows on the History page


@router.get("/history", response_class=HTMLResponse)
def history(request: Request) -> Response:
    services = request.app.state.services
    ctx = view_context(services) | {"current": "/history",
                                    "history": filed_discs(services, LIMIT),
                                    "set_pos": set_positions(services)}
    return TEMPLATES.TemplateResponse(request, "history.html", ctx)


def set_positions(services) -> dict[int, tuple[int, int]]:
    """Disc id -> (its number, the highest number filed) for video Discs in a set of 2 or more."""
    out = {}
    for kind in SetKind:
        for s in services.sets.filed(kind):
            if len(s.members) > 1:
                out |= {disc_id: (n, max(s.numbers)) for disc_id, n in s.members}
    return out


@router.get("/covers/{name}")
def cover(request: Request, name: str) -> FileResponse:
    path = request.app.state.services.covers.path(name)
    if path is None:
        raise HTTPException(404, "No such cover")
    return FileResponse(path, headers={"Cache-Control": "max-age=86400"})
