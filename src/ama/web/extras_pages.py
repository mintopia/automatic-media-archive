"""Sorting an archived film's Extras: optional, never blocks archiving.

`GET /jobs/{id}/extras` lists the Extras archived to the film's folder with their
stills (taken before scratch was deleted), a name and a Plex category each.
Saving moves the changed ones to their Plex folder (`MovieArchiver.sort_extras`);
"Leave as they are" just takes the Disc off the Review page's optional list.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response

from ama.jobs import JobRecord, JobStatus, TitleRecord
from ama.extras import Category, Extra, ExtraStatus
from ama.retry import RetryLater
from ama.moviereview import POSITIONS, short_duration
from ama.video_rip import VIDEO_DISC_TYPES
from ama.web import TEMPLATES, view_context
from ama.web.review_items import after_decision
from ama.events import Topic

router = APIRouter()


@dataclass(frozen=True)
class ExtraRow:
    extra: Extra
    title: TitleRecord | None
    stills: tuple[tuple[int, str | None], ...]  # (pct, src or None)

    @property
    def note(self) -> str:
        n = f"Title {self.extra.title_number} on the Disc"
        if self.title is None:
            return n
        s = self.title.duration_s
        return f"{n} · {short_duration(s) if s >= 3600 else f'{max(1, round(s / 60))} min'}"


@dataclass(frozen=True)
class ToSort:
    """An archived film whose Extras nobody has looked at yet (the Review page's optional list)."""

    record: JobRecord
    extras: int

    @property
    def href(self) -> str:
        return f"/jobs/{self.record.id}/extras"


def to_sort(services) -> list[ToSort]:
    out = []
    for job_id in services.movie_archive.extras.to_sort():
        rec = services.jobs.get(job_id)
        if rec is not None and rec.status == JobStatus.ARCHIVED:
            out.append(ToSort(rec, len(_archived(services, job_id))))
    return out


def _services(request: Request):
    return request.app.state.services


def _archived(services, job_id: int) -> list[Extra]:
    return [e for e in services.movie_archive.extras.of(job_id)
            if e.status == ExtraStatus.ARCHIVED]


def _archived_movie(services, job_id: int) -> JobRecord:
    rec = services.jobs.get(job_id)
    if (rec is None or rec.disc_type not in VIDEO_DISC_TYPES or rec.status != JobStatus.ARCHIVED
            or not _archived(services, job_id)):
        raise HTTPException(404, "This Disc has no archived Extras")
    return rec


def _page(request: Request, services, rec: JobRecord, errors: list[str] | None = None,
          status_code: int = 200) -> Response:
    store = services.movie_archive.extras
    titles = {t.number: t for t in rec.titles}
    rows = [ExtraRow(e, titles.get(e.title_number), tuple(
                (pct, f"/jobs/{rec.id}/extras/{e.title_number}/{pct}.jpg"
                 if store.still(rec.id, e.title_number, pct).is_file() else None)
                for pct in POSITIONS))
            for e in _archived(services, rec.id)]
    ctx = view_context(services) | {
        "current": "/review", "record": rec, "rows": rows, "categories": list(Category),
        "errors": errors or []}
    return TEMPLATES.TemplateResponse(request, "review_extras.html", ctx,
                                      status_code=status_code)


@router.get("/jobs/{job_id}/extras", response_class=HTMLResponse)
def extras_page(request: Request, job_id: int) -> Response:
    services = _services(request)
    return _page(request, services, _archived_movie(services, job_id))


@router.get("/jobs/{job_id}/extras/{number}/{pct}.jpg")
def still(request: Request, job_id: int, number: int, pct: int) -> Response:
    path = _services(request).movie_archive.extras.still(job_id, number, pct)
    if pct not in POSITIONS or not path.is_file():
        raise HTTPException(404, "No such picture")
    return FileResponse(path, media_type="image/jpeg")


@router.post("/jobs/{job_id}/extras", response_class=HTMLResponse)
async def save(request: Request, job_id: int) -> Response:
    services = _services(request)
    rec = _archived_movie(services, job_id)
    form = await request.form()
    changes: dict[int, tuple[str, Category]] = {}
    for e in _archived(services, job_id):
        n = e.title_number
        raw = str(form.get(f"category_{n}", e.category.value))
        try:
            category = Category(raw)
        except ValueError:
            raise HTTPException(400, f"{raw} isn't a Plex extras category") from None
        changes[n] = (str(form.get(f"name_{n}", e.name)), category)
    try:
        await asyncio.to_thread(services.movie_archive.sort_extras, rec, changes)
    except RetryLater as e:
        return _page(request, services, rec, [f"{e}. Nothing was lost; try again."],
                     status_code=503)
    services.bus.publish(Topic.REVIEW)
    return after_decision(request, rec.id, f"Saved the Extras of {rec.title}",
                          "Plex finds each one in its category's folder.")


@router.post("/jobs/{job_id}/extras/leave")
async def leave(request: Request, job_id: int) -> Response:
    services = _services(request)
    _archived_movie(services, job_id)
    services.movie_archive.extras.mark_reviewed(job_id)
    services.bus.publish(Topic.REVIEW)
    return RedirectResponse("/review", status_code=303)
