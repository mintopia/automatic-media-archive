"""Routes for one Disc: its Rip (live or finished), or why it failed."""

from __future__ import annotations

from dataclasses import replace
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response

from ama.jobs import JobRecord, JobStatus, FailureKind
from ama.drive import DiscType
from ama.encoder import EncodeStatus
from ama.extras import ExtraStatus
from ama.media import Album, Screen
from ama.web import TEMPLATES, view_context
from ama.events import Topic

router = APIRouter()


def _job_or_404(services, job_id: int) -> JobRecord:
    job = services.jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "No such Job")
    return job


@router.get("/disc", response_class=HTMLResponse)
def disc_in_drive(request: Request) -> Response:
    """The video Disc being ripped, live. Once it's done, its record page."""
    services = request.app.state.services
    ripper = services.video_rip
    if ripper.active is None:
        return RedirectResponse(f"/jobs/{ripper.job.id}" if ripper.job else "/", status_code=303)
    ctx = view_context(services) | {"current": "/", "live": True}
    return TEMPLATES.TemplateResponse(request, "job.html", ctx)


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_page(request: Request, job_id: int) -> Response:
    services = request.app.state.services
    rec = _job_or_404(services, job_id)
    if rec.disc_type == DiscType.CD:
        return _cd_page(request, services, rec)
    return _video_page(request, services, rec)


def _section(rec: JobRecord) -> str:
    """The nav section a Disc's page is in: History once it's Ripped (failures stay on Now)."""
    return "/" if rec.status in (JobStatus.RIPPING, JobStatus.FAILED) else "/history"


def _cd_page(request: Request, services, rec: JobRecord) -> Response:
    ctx = view_context(services) | {"current": _section(rec), "record": rec}
    if rec.status == JobStatus.FAILED:
        tracks = services.cd.job(rec.id).tracks
        ctx |= {"log": services.jobs.log_lines(rec.id), "track_count": len(tracks)}
        return TEMPLATES.TemplateResponse(request, "cd_failed.html", ctx)
    cd = services.cd.current
    live = cd is not None and cd.job_id == rec.id
    view = cd if live else services.cd.job(rec.id)
    album = services.media.get(rec.id) if rec.status == JobStatus.FILED else None
    if isinstance(album, Album):
        ctx |= {"view": replace(view, album=album), "album": album}
        return TEMPLATES.TemplateResponse(request, "job_cd_filed.html", ctx)
    ctx |= {"live": live, "view": view, "title": rec.title or rec.label or "Unknown CD"}
    return TEMPLATES.TemplateResponse(request, "job_cd.html", ctx)


def _video_page(request: Request, services, job: JobRecord) -> Response:
    active = services.video_rip.active
    if active is not None and active.id == job.id:
        return RedirectResponse("/disc", status_code=303)
    ctx = view_context(services) | {"current": _section(job), "job": job}
    if job.status == JobStatus.FAILED:
        ctx["log_lines"] = services.jobs.log_lines(job.id)
        licence = job.failure is not None and job.failure.kind == FailureKind.LICENCE
        ctx["log_open"] = not licence
        return TEMPLATES.TemplateResponse(
            request, "job_licence.html" if licence else "job_failed.html", ctx)
    filed = job.status == JobStatus.FILED
    screen = services.media.get(job.id) if filed else None
    ctx |= {"rip_job": job, "rip_progress": None, "live": False,
            "became": _what_titles_became(services, job.id) if filed else None,
            "screen": screen if isinstance(screen, Screen) else None,
            "extras_href": f"/jobs/{job.id}/extras" if job.status == JobStatus.FILED
            and any(e.status == ExtraStatus.FILED
                    for e in services.movie_archive.extras.of(job.id)) else None}
    return TEMPLATES.TemplateResponse(request, "job.html", ctx)


def _what_titles_became(services, job_id: int) -> dict[int, str]:
    """Title number -> what it was filed as; a Title left out isn't in it."""
    out: dict[int, str] = {}
    movie = services.movie_archive.movies.get(job_id)
    if movie is not None:
        out[movie.title_number] = "Main Feature"
    for e in services.movie_archive.extras.of(job_id):
        if e.status == ExtraStatus.FILED:
            out[e.title_number] = f"Extra · {e.category.value}"
    for t in services.tv_archive.titles.for_job(job_id):
        if t.status != EncodeStatus.FILED:
            continue
        ep = t.episode
        out[t.title_number] = (f"{ep.code} · {ep.name}" if ep.name else ep.code) if ep else "Extra"
    return out


@router.get("/jobs/{job_id}/waiting", response_class=HTMLResponse)
def job_waiting(request: Request, job_id: int) -> Response:
    """The Job's Waiting line (or nothing); its page re-fetches it on every `problems` event."""
    services = request.app.state.services
    _job_or_404(services, job_id)
    return TEMPLATES.TemplateResponse(request, "partials/job_waiting.html",
                                      {"job_id": job_id, "waiting_for": services.problems.why})


@router.get("/jobs/{job_id}/log", response_class=PlainTextResponse)
def job_log(request: Request, job_id: int) -> str:
    services = request.app.state.services
    _job_or_404(services, job_id)
    return "\n".join(map(str, services.jobs.log_lines(job_id))) + "\n"


@router.post("/jobs/{job_id}/dismiss")
def dismiss(request: Request, job_id: int) -> Response:
    """Take a failed Disc off Now. Inserting it again Rips it from the start."""
    services = request.app.state.services
    rec = _job_or_404(services, job_id)
    if rec.status == JobStatus.FAILED:
        services.jobs.dismiss(job_id)
        services.bus.publish(Topic.RIP)
        services.bus.publish(Topic.DRIVE)
    return RedirectResponse("/", status_code=303)
