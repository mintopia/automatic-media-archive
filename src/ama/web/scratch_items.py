"""What holds scratch: one row per Disc whose files are on scratch, for the scratch page.

`scratch_context(services)` is reached through `view_context`'s lazy `scratch_view`, so
only templates that show it (the scratch page and its live fragments) walk scratch.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ama.discs import DiscRecord, DiscStatus
from ama.moviearchive import EncodeStatus
from ama.phase import Phase
from ama.scratch import GB
from ama.web.review_items import review_items

if TYPE_CHECKING:
    from ama.app import Services


@dataclass(frozen=True)
class ScratchItem:
    """One Disc's files on scratch, as the "Using scratch" bin lists it."""

    record: DiscRecord
    title: str
    state: str           # e.g. "Needs Review · choose edition"
    gb: int              # whole GB, rounded up
    sticker: Phase | None = None  # its status chip
    href: str = ""       # its Review, when it waits for one


def dir_bytes(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.stat(os.path.join(root, name)).st_size
            except OSError:
                pass
    return total


def scratch_items(services: Services) -> list[ScratchItem]:
    """Discs whose Rip is on scratch: Ripping, then Needs Review, then waiting to encode/file."""
    discs = services.discs
    ripping, waiting = [], []
    for rec in sorted(discs.list(DiscStatus.RIPPING, include_dismissed=True), key=lambda r: r.id):
        ripping.append(_item(rec, rec.name, f"Ripping · {_rip_pct(services, rec)}%",
                             sticker=Phase.RIPPING))
    review = [_item(i.record, i.title, f"Needs Review · {i.action.lower()}", href=i.href)
              for i in review_items(services)]
    job = services.movie_archive.encoder.current
    movies = services.movie_archive.movies
    for rec in sorted(discs.list(DiscStatus.RIPPED, include_dismissed=True), key=lambda r: r.id):
        movie = movies.get(rec.id)
        tv = services.tv_archive.titles.for_disc(rec.id)
        if tv:
            waiting.append(_item(rec, tv[0].series.title, "TV · encoding and filing Episodes",
                                 Phase.ENCODING))
        elif movie is None:
            waiting.append(_item(rec, rec.name, "Being identified"))
        elif job is not None and job.disc.id == rec.id:
            waiting.insert(0, _item(rec, movie.film.name,
                                    f"Encoding · {job.progress.pct}%", Phase.ENCODING))
        elif movie.status == EncodeStatus.FAILED:
            waiting.append(_item(rec, movie.film.name, "The Encode didn't work",
                                 Phase.FAILED))
        elif movie.status == EncodeStatus.ENCODED:
            waiting.append(_item(rec, movie.film.name, "Encoded · filing to the NAS"))
        else:
            waiting.append(_item(rec, movie.film.name, "Waiting to encode", Phase.ENCODING))
    return [*ripping, *review, *waiting]


def _item(rec: DiscRecord, title: str, state: str, sticker: Phase | None = None,
          href: str = "") -> ScratchItem:
    gb = math.ceil(dir_bytes(rec.scratch_dir) / GB) if rec.scratch_dir.exists() else 0
    return ScratchItem(rec, title, state, gb, sticker, href)


def _rip_pct(services: Services, rec: DiscRecord) -> int:
    cd = services.cd.current
    if cd is not None and cd.disc_id == rec.id:
        return int(cd.percent)
    progress = services.video_rip.progress
    active = services.video_rip.active
    return progress.pct if progress and active and active.id == rec.id else 0


def scratch_context(services: Services) -> dict:
    items = scratch_items(services)
    job = services.movie_archive.encoder.current
    freeing = next((i for i in items if job and i.record.id == job.disc.id), None)
    return {"scratch_items": items, "scratch_items_gb": sum(i.gb for i in items),
            "encode_freeing": (freeing.gb, job.progress.eta_s) if freeing and job else None}
