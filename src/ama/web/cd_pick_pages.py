"""Picking the release of the CD being ripped, from its rip card (cdguess.py).

`GET /jobs/{id}/release` lists every MusicBrainz release that fits the Rip, the one
shown now selected; `POST` stores the pick on the Job and goes back to the rip card.
Once the Rip is over, Review decides instead (it offers the pick pre-selected).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response

from ama.cdguess import value
from ama.cdrip import NotOffered, NotRipping
from ama.web import TEMPLATES, view_context
from ama.web.review_pages import cd_editions

router = APIRouter()


def _live(services, job_id: int):
    cd = services.cd.current
    return cd if cd is not None and cd.job_id == job_id and cd.guess else None


@router.get("/jobs/{job_id}/release", response_class=HTMLResponse)
def picker(request: Request, job_id: int) -> Response:
    services = request.app.state.services
    cd = _live(services, job_id)
    if cd is None:
        return RedirectResponse(f"/jobs/{job_id}", status_code=303)
    ctx = view_context(services) | {
        "current": "/", "job_id": job_id, "cd": cd, "selected": value(cd.guess.match),
        "editions": cd_editions(list(cd.guess.candidates), cd.tracks)}
    return TEMPLATES.TemplateResponse(request, "cd_release.html", ctx)


@router.post("/jobs/{job_id}/release")
async def pick(request: Request, job_id: int,
               release: Annotated[str, Form()] = "") -> Response:
    services = request.app.state.services
    try:
        await services.cd.pick(job_id, release)
    except NotRipping:
        raise HTTPException(409, "This CD isn't ripping any more: pick its edition in Review")
    except NotOffered:
        raise HTTPException(400, "That release isn't one that fits this CD")
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


@router.get("/jobs/{job_id}/release/cover/{release_id}")
async def cover(request: Request, job_id: int, release_id: str) -> Response:
    """A release's front cover, for the picker (only releases offered for the CD ripping)."""
    services = request.app.state.services
    cd = _live(services, job_id)
    match = next((m for m in cd.guess.candidates if m.release.id == release_id), None) \
        if cd else None
    name = await services.cd.cover(match) if match and match.release.has_front is not False \
        else None
    path = services.covers.path(name) if name else None
    if path is None:
        raise HTTPException(404, "No cover")
    return FileResponse(path, headers={"Cache-Control": "max-age=86400"})
