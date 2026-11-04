"""Sorting a filed film's Extras (#8): optional, never blocks filing.

`GET /discs/{id}/extras` lists the Extras filed to the film's folder with their
stills (taken before scratch was deleted), a name and a Plex category each.
Saving moves the changed ones to their Plex folder (`MovieArchiver.sort_extras`);
"Leave as they are" just takes the Disc off the Review page's optional list.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response

from ama import review
from ama.discs import DiscRecord, DiscStatus, TitleRecord
from ama.extras import Category, Extra, ExtraStatus
from ama.moviearchive import RetryLater
from ama.moviereview import POSITIONS, short_duration
from ama.video_rip import VIDEO_DISC_TYPES
from ama.web import TEMPLATES, view_context

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
    """A filed film whose Extras nobody has looked at yet (the Review page's optional list)."""

    record: DiscRecord
    extras: int

    @property
    def href(self) -> str:
        return f"/discs/{self.record.id}/extras"


def to_sort(services) -> list[ToSort]:
    out = []
    for disc_id in services.movie_archive.extras.to_sort():
        rec = services.discs.get(disc_id)
        if rec is not None and rec.status == DiscStatus.FILED:
            out.append(ToSort(rec, len(_filed(services, disc_id))))
    return out


def _services(request: Request):
    return request.app.state.services


def _filed(services, disc_id: int) -> list[Extra]:
    return [e for e in services.movie_archive.extras.of(disc_id)
            if e.status == ExtraStatus.FILED]


def _filed_movie(services, disc_id: int) -> DiscRecord:
    rec = services.discs.get(disc_id)
    if (rec is None or rec.disc_type not in VIDEO_DISC_TYPES or rec.status != DiscStatus.FILED
            or not _filed(services, disc_id)):
        raise HTTPException(404, "This Disc has no filed Extras")
    return rec


def _page(request: Request, services, rec: DiscRecord, errors: list[str] | None = None,
          status_code: int = 200) -> Response:
    store = services.movie_archive.extras
    titles = {t.number: t for t in rec.titles}
    rows = [ExtraRow(e, titles.get(e.title_number), tuple(
                (pct, f"/discs/{rec.id}/extras/{e.title_number}/{pct}.jpg"
                 if store.still(rec.id, e.title_number, pct).is_file() else None)
                for pct in POSITIONS))
            for e in _filed(services, rec.id)]
    ctx = view_context(services) | {
        "current": "/review", "record": rec, "rows": rows, "categories": list(Category),
        "errors": errors or []}
    return TEMPLATES.TemplateResponse(request, "review_extras.html", ctx,
                                      status_code=status_code)


@router.get("/discs/{disc_id}/extras", response_class=HTMLResponse)
def extras_page(request: Request, disc_id: int) -> Response:
    services = _services(request)
    return _page(request, services, _filed_movie(services, disc_id))


@router.get("/discs/{disc_id}/extras/{number}/{pct}.jpg")
def still(request: Request, disc_id: int, number: int, pct: int) -> Response:
    path = _services(request).movie_archive.extras.still(disc_id, number, pct)
    if pct not in POSITIONS or not path.is_file():
        raise HTTPException(404, "No such picture")
    return FileResponse(path, media_type="image/jpeg")


@router.post("/discs/{disc_id}/extras", response_class=HTMLResponse)
async def save(request: Request, disc_id: int) -> Response:
    services = _services(request)
    rec = _filed_movie(services, disc_id)
    form = await request.form()
    changes: dict[int, tuple[str, Category]] = {}
    for e in _filed(services, disc_id):
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
    services.bus.publish(review.TOPIC)
    return RedirectResponse("/review", status_code=303)


@router.post("/discs/{disc_id}/extras/leave")
async def leave(request: Request, disc_id: int) -> Response:
    services = _services(request)
    _filed_movie(services, disc_id)
    services.movie_archive.extras.mark_reviewed(disc_id)
    services.bus.publish(review.TOPIC)
    return RedirectResponse("/review", status_code=303)
