"""Routes for one Job's page (#41): its Rip (live or finished), its Steps, or why it failed.

`/jobs/{id}` is the one page every link to a Job opens (rip card, Encoding row,
Review, History); its breadcrumb follows the Job's Phase (`job_steps.section`)."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response

from ama import cdreview
from ama.cdguess import value
from ama.jobs import JobRecord, JobStatus, FailureKind
from ama.drive import DiscType
from ama.encoder import EncodeStatus
from ama.extras import ExtraStatus
from ama.media import Album, Screen
from ama.web import TEMPLATES, view_context
from ama.web.job_steps import job_steps, section
from ama.events import Topic

router = APIRouter()


def _job_or_404(services, job_id: int) -> JobRecord:
    job = services.jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "No such Job")
    return job


@router.get("/disc", response_class=HTMLResponse)
def disc_in_drive(request: Request) -> Response:
    """The video Disc being ripped (else the last one): its Job page."""
    ripper = request.app.state.services.video_rip
    job = ripper.active or ripper.job
    return RedirectResponse(f"/jobs/{job.id}" if job else "/", status_code=303)


@router.get("/discs/{rest:path}")
def old_disc_url(rest: str) -> Response:
    """v1 linked Jobs as /discs/{id}; keep those bookmarks working."""
    return RedirectResponse(f"/jobs/{rest}", status_code=301)


def _job_context(services, rec: JobRecord) -> dict:
    """What every Job page has: its Steps, and the nav section its Phase puts it in."""
    where = section(rec)
    steps = job_steps(services, rec)
    identified = next((s.subject for s in steps if s.name == "Identification"), "")
    unnamed = "Unknown CD" if rec.disc_type == DiscType.CD else rec.disc_type.long_name
    return {"job": rec, "steps": steps, "now": datetime.now(), "section": where,
            "current": where.href, "job_name": rec.title or identified or rec.label or unnamed}


@router.get("/jobs/{job_id}/steps", response_class=HTMLResponse)
def steps(request: Request, job_id: int) -> Response:
    """The Steps section alone: the page re-fetches it whenever the pipeline moves."""
    services = request.app.state.services
    ctx = _job_context(services, _job_or_404(services, job_id)) | {"oob": True}  # + crumb
    return TEMPLATES.TemplateResponse(request, "partials/job_steps.html", ctx)


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_page(request: Request, job_id: int) -> Response:
    services = request.app.state.services
    rec = _job_or_404(services, job_id)
    if rec.disc_type == DiscType.CD:
        return _cd_page(request, services, rec)
    return _video_page(request, services, rec)


def _cd_page(request: Request, services, rec: JobRecord) -> Response:
    ctx = view_context(services) | _job_context(services, rec) | {"record": rec}
    if rec.status == JobStatus.FAILED:
        ctx["track_count"] = len(services.cd.job(rec.id).tracks)
        return TEMPLATES.TemplateResponse(request, "cd_failed.html", ctx)
    cd = services.cd.current
    live = cd is not None and cd.job_id == rec.id
    view = cd if live else services.cd.job(rec.id)
    album = services.media.get(rec.id) if rec.status == JobStatus.FILED else None
    if isinstance(album, Album):
        ctx |= {"view": replace(view, album=album), "album": album}
        return TEMPLATES.TemplateResponse(request, "job_cd_filed.html", ctx)
    if not live and view.pick:
        match = next((m for m in cdreview.candidates(rec.scratch_dir, view.tracks)
                      if value(m) == view.pick.value), None)
        if match:
            view = replace(view, picked_titles={t.number: t.title for t in match.tracks})
    ctx |= {"live": live, "view": view}
    if not live and view.pick and not rec.title:
        ctx["job_name"] = view.pick.album
    return TEMPLATES.TemplateResponse(request, "job_cd.html", ctx)


def _video_page(request: Request, services, job: JobRecord) -> Response:
    active = services.video_rip.active
    ctx = view_context(services) | _job_context(services, job)
    if active is not None and active.id == job.id:
        return TEMPLATES.TemplateResponse(request, "job.html", ctx | {"live": True})
    if job.status == JobStatus.FAILED and job.scratch_cleaned_at is None:
        licence = job.failure is not None and job.failure.kind == FailureKind.LICENCE
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


@router.post("/jobs/{job_id}/titles/{number}")
async def tick_title(request: Request, job_id: int, number: int) -> Response:
    """Tick (`rip` sent) or untick a Title of the Rip under way that hasn't started (ADR 0005):
    unticked, it is Skipped. 409 if it can't be: it's ripping or done, or the Rip is over."""
    services = request.app.state.services
    _job_or_404(services, job_id)
    rip = "rip" in (await request.form())
    if not services.video_rip.skip(job_id, number, skipped=not rip):
        return Response(status_code=409)
    return Response(status_code=204)


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
