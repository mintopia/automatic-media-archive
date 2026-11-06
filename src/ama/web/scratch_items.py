"""What holds scratch: one row per Job whose files are on scratch, for the scratch page.

`scratch_context(services)` is reached through `view_context`'s lazy `scratch_view`, so
only templates that show it (the scratch page and its live fragments) walk scratch.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ama.jobs import JobRecord, JobStatus
from ama.moviearchive import EncodeStatus
from ama.phase import Phase
from ama.scratch import GB, dir_bytes
from ama.web.review_items import review_items

if TYPE_CHECKING:
    from ama.app import Services


@dataclass(frozen=True)
class ScratchItem:
    """One Disc's files on scratch, as the "Using scratch" bin lists it."""

    record: JobRecord
    title: str
    state: str           # e.g. "Needs Review · choose edition"
    gb: int              # whole GB, rounded up
    sticker: Phase | None = None  # its status chip
    href: str = ""       # its Review, when it waits for one


def scratch_items(services: Services) -> list[ScratchItem]:
    """Discs whose Rip is on scratch: Ripping, then Needs Review, then waiting to encode/file."""
    jobs = services.jobs
    ripping, waiting = [], []
    for rec in sorted(jobs.list(JobStatus.RIPPING, include_dismissed=True), key=lambda r: r.id):
        ripping.append(_item(rec, rec.name, f"Ripping · {_rip_pct(services, rec)}%",
                             sticker=Phase.RIPPING))
    review = [_item(i.record, i.title, f"Needs Review · {i.action.lower()}", href=i.href)
              for i in review_items(services)]
    encode = services.movie_archive.encoder.current
    movies = services.movie_archive.movies
    for rec in sorted(jobs.list(JobStatus.RIPPED, include_dismissed=True), key=lambda r: r.id):
        movie = movies.get(rec.id)
        tv = services.tv_archive.titles.for_job(rec.id)
        if tv:
            waiting.append(_item(rec, tv[0].series.title, "TV · encoding and archiving Episodes",
                                 Phase.ENCODING))
        elif movie is None:
            waiting.append(_item(rec, rec.name, "Being identified"))
        elif encode is not None and encode.job.id == rec.id:
            waiting.insert(0, _item(rec, movie.film.name,
                                    f"Encoding · {encode.progress.pct}%", Phase.ENCODING))
        elif movie.status == EncodeStatus.FAILED:
            waiting.append(_item(rec, movie.film.name, "The Encode didn't work",
                                 Phase.FAILED))
        elif movie.status == EncodeStatus.ENCODED:
            waiting.append(_item(rec, movie.film.name, "Encoded · archiving"))
        else:
            waiting.append(_item(rec, movie.film.name, "Waiting to encode", Phase.ENCODING))
    return [*ripping, *review, *waiting]


def _item(rec: JobRecord, title: str, state: str, sticker: Phase | None = None,
          href: str = "") -> ScratchItem:
    gb = math.ceil(dir_bytes(rec.scratch_dir) / GB) if rec.scratch_dir.exists() else 0
    return ScratchItem(rec, title, state, gb, sticker, href)


def _rip_pct(services: Services, rec: JobRecord) -> int:
    cd = services.cd.current
    if cd is not None and cd.job_id == rec.id:
        return int(cd.percent)
    progress = services.video_rip.progress
    active = services.video_rip.active
    return progress.pct if progress and active and active.id == rec.id else 0


def scratch_context(services: Services) -> dict:
    items = scratch_items(services)
    return {"scratch_items": items, "scratch_items_gb": sum(i.gb for i in items)}
