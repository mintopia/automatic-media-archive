"""Routes for one Disc: its Rip (live or finished), or why it failed."""

from __future__ import annotations

from dataclasses import replace
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response

from ama.discs import DiscRecord, DiscStatus, FailureKind
from ama.drive import DiscType
from ama.encoder import EncodeStatus
from ama.extras import ExtraStatus
from ama.media import Album, Screen
from ama.web import TEMPLATES, view_context
from ama.events import Topic

router = APIRouter()


def _disc_or_404(services, disc_id: int) -> DiscRecord:
    disc = services.discs.get(disc_id)
    if disc is None:
        raise HTTPException(404, "No such Disc")
    return disc


@router.get("/disc", response_class=HTMLResponse)
def disc_in_drive(request: Request) -> Response:
    """The video Disc being ripped, live. Once it's done, its record page."""
    services = request.app.state.services
    ripper = services.video_rip
    if ripper.active is None:
        return RedirectResponse(f"/discs/{ripper.disc.id}" if ripper.disc else "/", status_code=303)
    ctx = view_context(services) | {"current": "/", "live": True}
    return TEMPLATES.TemplateResponse(request, "disc.html", ctx)


@router.get("/discs/{disc_id}", response_class=HTMLResponse)
def disc_page(request: Request, disc_id: int) -> Response:
    services = request.app.state.services
    rec = _disc_or_404(services, disc_id)
    if rec.disc_type == DiscType.CD:
        return _cd_page(request, services, rec)
    return _video_page(request, services, rec)


def _section(rec: DiscRecord) -> str:
    """The nav section a Disc's page is in: History once it's Ripped (failures stay on Now)."""
    return "/" if rec.status in (DiscStatus.RIPPING, DiscStatus.FAILED) else "/history"


def _cd_page(request: Request, services, rec: DiscRecord) -> Response:
    ctx = view_context(services) | {"current": _section(rec), "record": rec}
    if rec.status == DiscStatus.FAILED:
        tracks = services.cd.disc(rec.id).tracks
        ctx |= {"log": services.discs.log_lines(rec.id), "track_count": len(tracks)}
        return TEMPLATES.TemplateResponse(request, "cd_failed.html", ctx)
    cd = services.cd.current
    live = cd is not None and cd.disc_id == rec.id
    view = cd if live else services.cd.disc(rec.id)
    album = services.media.get(rec.id) if rec.status == DiscStatus.FILED else None
    if isinstance(album, Album):
        ctx |= {"view": replace(view, album=album), "album": album}
        return TEMPLATES.TemplateResponse(request, "disc_cd_filed.html", ctx)
    ctx |= {"live": live, "view": view, "title": rec.title or rec.label or "Unknown CD"}
    return TEMPLATES.TemplateResponse(request, "disc_cd.html", ctx)


def _video_page(request: Request, services, disc: DiscRecord) -> Response:
    active = services.video_rip.active
    if active is not None and active.id == disc.id:
        return RedirectResponse("/disc", status_code=303)
    ctx = view_context(services) | {"current": _section(disc), "disc": disc}
    if disc.status == DiscStatus.FAILED:
        ctx["log_lines"] = services.discs.log_lines(disc.id)
        licence = disc.failure is not None and disc.failure.kind == FailureKind.LICENCE
        ctx["log_open"] = not licence
        return TEMPLATES.TemplateResponse(
            request, "disc_licence.html" if licence else "disc_failed.html", ctx)
    filed = disc.status == DiscStatus.FILED
    screen = services.media.get(disc.id) if filed else None
    ctx |= {"rip_disc": disc, "rip_progress": None, "live": False,
            "became": _what_titles_became(services, disc.id) if filed else None,
            "screen": screen if isinstance(screen, Screen) else None,
            "extras_href": f"/discs/{disc.id}/extras" if disc.status == DiscStatus.FILED
            and any(e.status == ExtraStatus.FILED
                    for e in services.movie_archive.extras.of(disc.id)) else None}
    return TEMPLATES.TemplateResponse(request, "disc.html", ctx)


def _what_titles_became(services, disc_id: int) -> dict[int, str]:
    """Title number -> what it was filed as; a Title left out isn't in it."""
    out: dict[int, str] = {}
    movie = services.movie_archive.movies.get(disc_id)
    if movie is not None:
        out[movie.title_number] = "Main Feature"
    for e in services.movie_archive.extras.of(disc_id):
        if e.status == ExtraStatus.FILED:
            out[e.title_number] = f"Extra · {e.category.value}"
    for t in services.tv_archive.titles.for_disc(disc_id):
        if t.status != EncodeStatus.FILED:
            continue
        ep = t.episode
        out[t.title_number] = (f"{ep.code} · {ep.name}" if ep.name else ep.code) if ep else "Extra"
    return out


@router.get("/discs/{disc_id}/waiting", response_class=HTMLResponse)
def disc_waiting(request: Request, disc_id: int) -> Response:
    """The Job's Waiting line (or nothing); its page re-fetches it on every `problems` event."""
    services = request.app.state.services
    _disc_or_404(services, disc_id)
    return TEMPLATES.TemplateResponse(request, "partials/job_waiting.html",
                                      {"disc_id": disc_id, "waiting_for": services.problems.why})


@router.get("/discs/{disc_id}/log", response_class=PlainTextResponse)
def disc_log(request: Request, disc_id: int) -> str:
    services = request.app.state.services
    _disc_or_404(services, disc_id)
    return "\n".join(map(str, services.discs.log_lines(disc_id))) + "\n"


@router.post("/discs/{disc_id}/dismiss")
def dismiss(request: Request, disc_id: int) -> Response:
    """Take a failed Disc off Now. Inserting it again Rips it from the start."""
    services = request.app.state.services
    rec = _disc_or_404(services, disc_id)
    if rec.status == DiscStatus.FAILED:
        services.discs.dismiss(disc_id)
        services.bus.publish(Topic.RIP)
        services.bus.publish(Topic.DRIVE)
    return RedirectResponse("/", status_code=303)
