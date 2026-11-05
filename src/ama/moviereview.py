"""Movie Review: what the Review page needs beyond the Encode pipeline.

- `Thumbnailer` (background task): for every video Disc waiting in Review, takes a
  still from each ripped Title at 10/50/90% of its runtime, from the Rip in
  scratch (`thumbs/t<title>_<pct>.jpg`; written to a temp name, then renamed, so a
  cut-off grab is retaken). A grab that fails is not retried until the app
  restarts; the page shows the Title without that picture.
- `saved_search`: the TMDB search Identification made (`tmdb.json`), the films offered first.

A decision (film + Main Feature) joins the Encode queue (`Movies.enqueue`) and the
Disc goes back to `ripped` (`JobStore.requeue`); `MovieArchiver` Encodes and files it.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from ama import review
from ama.jobs import JobRecord, JobStore, TitleRecord, TitleStatus
from ama.moviearchive import TMDB_FILE  # the search MovieArchiver.identify saved
from ama.proc import Streamer
from ama.tmdb import RUNTIME_TOLERANCE_S, Candidate
from ama.tools import ToolLookup, ToolUnavailable
from ama.video_rip import VIDEO_DISC_TYPES

log = logging.getLogger(__name__)

POSITIONS = (10, 50, 90)  # % of the Title's runtime
THUMBS = "thumbs"
WIDTH = 480  # px; the Review page shows them at up to ~100 px wide, 2x for HiDPI


def thumb_path(scratch_dir: Path, title_number: int, pct: int) -> Path:
    return scratch_dir / THUMBS / f"t{title_number}_{pct}.jpg"


def thumb_args(ffmpeg: Path, src: Path, at_s: float, dest: Path) -> list[str]:
    """One still at `at_s` seconds, square pixels (DVDs are anamorphic), WIDTH wide."""
    return [str(ffmpeg), "-hide_banner", "-nostdin", "-loglevel", "error",
            "-ss", f"{at_s:.1f}", "-i", str(src), "-frames:v", "1",
            "-vf", f"scale=trunc(iw*sar/2)*2:ih,scale={WIDTH}:-2", "-q:v", "5",
            "-y", str(dest)]


def ripped_titles(rec: JobRecord) -> list[TitleRecord]:
    return [t for t in rec.titles if t.status == TitleStatus.RIPPED]


@dataclass
class Thumbnailer:
    jobs: JobStore
    tool: ToolLookup
    streamer: Streamer
    interval: float
    failed: set[tuple[int, int, int]] = field(default_factory=set)  # (disc, title, pct)

    async def run(self) -> None:
        while True:
            try:
                await self.once()
            except Exception:
                log.exception("Taking Review thumbnails crashed")
            await asyncio.sleep(self.interval)

    def _missing(self) -> list[tuple[JobRecord, TitleRecord, int]]:
        return [(rec, t, pct)
                for rec in review.queue(self.jobs) if rec.disc_type in VIDEO_DISC_TYPES
                for t in ripped_titles(rec) for pct in POSITIONS
                if (rec.id, t.number, pct) not in self.failed
                and not thumb_path(rec.scratch_dir, t.number, pct).exists()]

    async def once(self) -> None:
        missing = self._missing()
        if not missing:
            return
        try:
            ffmpeg = self.tool("ffmpeg")
        except ToolUnavailable:
            return  # ffmpeg is still being fetched; next pass
        for rec, title, pct in missing:
            await asyncio.to_thread(self._grab, ffmpeg, rec, title, pct)

    def _grab(self, ffmpeg: Path, rec: JobRecord, title: TitleRecord, pct: int) -> None:
        dest = thumb_path(rec.scratch_dir, title.number, pct)
        tmp = dest.with_name(f"{dest.stem}.tmp.jpg")
        dest.parent.mkdir(exist_ok=True)
        lines: list[str] = []
        try:
            code = self.streamer(thumb_args(ffmpeg, rec.scratch_dir / title.file,
                                            title.duration_s * pct / 100, tmp), lines.append)
        except OSError as e:
            code, lines = -1, [str(e)]
        if code != 0 or not tmp.exists():
            tmp.unlink(missing_ok=True)
            self.failed.add((rec.id, title.number, pct))
            self.jobs.log(rec.id, f"Couldn't take a picture of Title {title.number} at {pct}% "
                                   f"(ffmpeg exit {code}{': ' + lines[-1] if lines else ''})",
                           error=True)
            return
        tmp.replace(dest)


# ---- the Review page's data ----------------------------------------------------



@dataclass(frozen=True)
class SavedSearch:
    terms: list[str]
    candidates: list[Candidate]


def saved_search(scratch_dir: Path) -> SavedSearch:
    try:
        data = json.loads((scratch_dir / TMDB_FILE).read_text(encoding="utf-8"))
        return SavedSearch([str(t) for t in data.get("terms", [])],
                           [Candidate(**c) for c in data.get("candidates", [])])
    except (OSError, ValueError, TypeError):
        return SavedSearch([], [])


def fits(film: Candidate, duration_s: int) -> bool:
    return bool(film.runtime_min) and abs(film.runtime_min * 60 - duration_s) <= RUNTIME_TOLERANCE_S


def short_duration(seconds: int, with_seconds: bool = False) -> str:
    """"2 h 50 m", "17 m", or with seconds "2 h 50 m 14 s"."""
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    parts = ([f"{h} h"] if h else []) + [f"{m} m"]
    if with_seconds:
        parts.append(f"{s} s")
    return " ".join(parts)


def runtime_note(film: Candidate, duration_s: int) -> str:
    """How the film's runtime compares with the chosen Title."""
    if not film.runtime_min:
        return "TMDB doesn't know its running time"
    if fits(film, duration_s):
        return "matches the Disc"
    diff = film.runtime_min * 60 - duration_s
    gap = short_duration(abs(diff) // 60 * 60)
    return f"{gap} {'longer' if diff > 0 else 'shorter'} than the Disc"

