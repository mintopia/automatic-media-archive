"""History: every filed Disc, newest first, and the cached cover art and posters."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

router = APIRouter()


@router.get("/covers/{name}")
def cover(request: Request, name: str) -> FileResponse:
    path = request.app.state.services.covers.path(name)
    if path is None:
        raise HTTPException(404, "No such cover")
    return FileResponse(path, headers={"Cache-Control": "max-age=86400"})
