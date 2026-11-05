"""TV Encode and filing.

Review keeps some of a TV Disc's Titles (`tvreview`): each is an Episode or an
Extra, with where it goes in the Archive (`tv.episode_path` / `tv.extra_path`),
queued in `tv_titles`. `TvArchiver` Encodes them one by one through the shared
`Encoder` to scratch `tv/t<n>.mkv`, files each as soon as it is Encoded, and once
every kept Title is filed marks the Disc filed (its scratch, the lossless Rip, is
deleted: ADR-0002) and asks Plex to scan the show. A failed Encode keeps the Rip;
it and any Encode cut short by a restart are queued again at the next start.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from ama import filing
from ama.archive import Archive, kind_of_path
from ama.config import LibraryKind
from ama.covers import Covers
from ama.db import Database
from ama.jobs import JobRecord, JobStatus, JobStore
from ama.encoder import PIPELINE_TOPICS, Encoder, EncodeQueue, EncodeStatus
from ama.events import EventBus
from ama.extras import default_names
from ama.media import MediaStore, screen
from ama.nas import NasMonitor
from ama.plex import Plex
from ama.problems import Problems
from ama.retry import Backoff, RetryLater
from ama.tmdb import Episode, Series, Tmdb, load_hints
from ama.tv import episode_path, extra_path
from ama.tvreview import Kept
from ama.video_rip import VIDEO_DISC_TYPES

log = logging.getLogger(__name__)

ENCODES = "tv"  # scratch subfolder for the Encodes


@dataclass(frozen=True)
class TvTitle:
    """A kept Title of a TV Disc and its place in the Encode queue."""

    job_id: int
    title_number: int
    series: Series
    episode: Episode | None  # None: an Extra
    path: PurePosixPath      # in the Archive
    status: EncodeStatus
    queued_at: datetime
    video_height: int = 0

    @property
    def name(self) -> str:
        """"The Office - s01e04 - The Quiz" (what the Encode is tagged and shown as)."""
        return self.path.stem


def planned(series: Series, rec: JobRecord, kept: Iterable[Kept]
            ) -> list[tuple[int, Episode | None, PurePosixPath]]:
    """(Title, Episode or None for an Extra, Archive path) for each kept Title. Extras are
    named as a film's are (`extras.default_names`)."""
    kept = list(kept)
    hints = load_hints(rec.scratch_dir, rec.label)
    names = default_names([k.title for k in kept if not k.episode],
                          (hints.disc_name, hints.volume_name, rec.label, series.name,
                           series.title), rec.label)
    return [(k.title.number, k.episode,
             episode_path(series, k.episode) if k.episode
             else extra_path(series, names[k.title.number])) for k in kept]


class TvTitles:
    def __init__(self, db: Database, now: Callable[[], datetime] = datetime.now) -> None:
        self._db = db
        self._now = now
        self._queue = EncodeQueue(db, "tv_titles", "encode_status")

    _COLS = ("job_id, title_number, tmdb_id, series, year, original_language, season, "
             "episode, episode_name, path, encode_status, queued_at, video_height")

    def _row(self, row) -> TvTitle:
        (job_id, number, tmdb_id, name, year, lang, season, episode, ep_name, path, status,
         queued, height) = row
        return TvTitle(job_id, number, Series(tmdb_id, name, year, lang),
                       Episode(season, episode, ep_name) if season is not None else None,
                       PurePosixPath(path), EncodeStatus(status), datetime.fromisoformat(queued),
                       height)

    def enqueue(self, job_id: int, series: Series,
                kept: Iterable[tuple[int, Episode | None, PurePosixPath]]) -> None:
        """Queue the Disc's kept Titles for Encode, replacing any earlier decision."""
        queued = self._now().isoformat(timespec="seconds")
        self._db.execute("DELETE FROM tv_titles WHERE job_id = ?", (job_id,))
        for number, ep, path in kept:
            self._db.execute(
                f"INSERT INTO tv_titles ({self._COLS}) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
                (job_id, number, series.id, series.name, series.year, series.original_language,
                 ep.season if ep else None, ep.number if ep else None, ep.name if ep else "",
                 path.as_posix(), EncodeStatus.QUEUED, queued))

    def has(self, job_id: int) -> bool:
        return self._db.execute("SELECT 1 FROM tv_titles WHERE job_id = ? LIMIT 1",
                                (job_id,)).fetchone() is not None

    def for_job(self, job_id: int) -> list[TvTitle]:
        rows = self._db.execute(f"SELECT {self._COLS} FROM tv_titles WHERE job_id = ? "
                                "ORDER BY title_number", (job_id,)).fetchall()
        return [self._row(r) for r in rows]

    def in_season(self, series_id: int, season: int) -> list[TvTitle]:
        """Every Disc's Episodes of the series' season (a set's earlier Discs)."""
        rows = self._db.execute(f"SELECT {self._COLS} FROM tv_titles WHERE tmdb_id = ? AND "
                                "season = ? AND path LIKE 'TV/%' ORDER BY episode",
                                (series_id, season)).fetchall()
        return [self._row(r) for r in rows]

    def queue(self) -> list[TvTitle]:
        """Kept Titles of Discs not yet filed, first in first out."""
        cols = ", ".join("q." + c.strip() for c in self._COLS.split(","))
        return [self._row(r) for r in
                self._queue.waiting(cols, "q.queued_at, q.job_id, q.title_number")]

    def set_status(self, job_id: int, number: int, status: EncodeStatus,
                   video_height: int | None = None) -> None:
        self._db.execute("UPDATE tv_titles SET encode_status = ?, "
                         "video_height = COALESCE(?, video_height) "
                         "WHERE job_id = ? AND title_number = ?",
                         (status.value, video_height, job_id, number))

    def requeue_unfinished(self) -> list[int]:
        """At startup: Encodes cut short, or failed, go back in the queue (Jobs affected)."""
        return self._queue.requeue(EncodeStatus.ENCODING, EncodeStatus.FAILED)


@dataclass(frozen=True)
class FiledTv:
    """A filed TV Disc, for the UI."""

    record: JobRecord
    episodes: list[TvTitle]


def encoded_path(rec: JobRecord, number: int) -> Path:
    return rec.scratch_dir / ENCODES / f"t{number}.mkv"


class TvArchiver:
    def __init__(self, jobs: JobStore, titles: TvTitles, encoder: Encoder,
                 nas: NasMonitor, archive: Archive, plex: Plex, bus: EventBus, interval: float,
                 retry_seconds: float = 60.0, clock: Callable[[], float] = time.monotonic, *,
                 tmdb: Tmdb, media: MediaStore, covers: Covers,
                 problems: Problems | None = None,
                 library: Callable[[JobRecord, LibraryKind], str | None] = lambda rec, kind: None
                 ) -> None:
        # The Library a Job files to; asking locks its pick (job_settings). None = default.
        self._library = library
        self._tmdb = tmdb
        self._media = media
        self._covers = covers
        self._jobs = jobs
        self.titles = titles
        self._encoder = encoder
        self._nas = nas
        self._archive = archive
        self._plex = plex
        self._bus = bus
        self._interval = interval
        self.backoff = Backoff(retry_seconds, clock, problems)

    async def run(self) -> None:
        self.recover()
        while True:
            await self.once()
            await asyncio.sleep(self._interval)

    def recover(self) -> None:
        for job_id in self.titles.requeue_unfinished():
            self._jobs.log(job_id, "Episode Encodes queued again after a restart")

    async def once(self) -> None:
        jobs = dict.fromkeys(t.job_id for t in self.titles.queue())
        for job_id in jobs:
            if not self.backoff.due(job_id):
                continue
            rec = self._jobs.get(job_id)
            assert rec is not None
            try:
                await self._advance(rec)
            except RetryLater as e:
                if self.backoff.later(job_id, str(e), e.problem):
                    self._jobs.log(job_id, f"{e}; trying again in a while", error=True)
            except Exception:
                log.exception("TV Encode/filing of Job %s crashed", job_id)
                self._jobs.log(job_id, "The Encode or filing went wrong (see the app's log "
                                         "file); trying again in a while", error=True)
                self.backoff.later(job_id, "The Encode or filing went wrong (see the app's log file)")
            else:
                self.backoff.done(job_id)
            finally:
                self._publish()

    async def _advance(self, rec: JobRecord) -> None:
        """Encode and file what's left of the Disc's kept Titles; file the Disc when done."""
        titles = {t.number: t for t in rec.titles}
        for row in self.titles.for_job(rec.id):
            if row.status in (EncodeStatus.QUEUED, EncodeStatus.ENCODING):
                ffmpeg, ffprobe = self._encoder.tools()
                out = encoded_path(rec, row.title_number)
                out.parent.mkdir(exist_ok=True)
                self.titles.set_status(rec.id, row.title_number, EncodeStatus.ENCODING)
                self._publish()
                height = await self._encoder.encode_title(
                    rec, titles[row.title_number], row.name, row.series.original_language,
                    out, ffmpeg, ffprobe)
                if height is None:
                    self.titles.set_status(rec.id, row.title_number, EncodeStatus.FAILED)
                    self._jobs.encode_failed(rec.id)
                    continue
                self.titles.set_status(rec.id, row.title_number, EncodeStatus.ENCODED, height)
                row = next(r for r in self.titles.for_job(rec.id)
                           if r.title_number == row.title_number)
            if row.status == EncodeStatus.ENCODED:
                await asyncio.to_thread(self._file_one, rec, row)
        rows = self.titles.for_job(rec.id)
        if rows and all(r.status == EncodeStatus.FILED for r in rows):
            await asyncio.to_thread(self._finish, rec, rows)

    def _file_one(self, rec: JobRecord, row: TvTitle) -> None:
        self._jobs.begin_step(rec.id, "file", "File", fresh=False)
        filing.require_nas(self._nas)
        src = encoded_path(rec, row.title_number)
        library = self._library(rec, kind_of_path(row.path) or LibraryKind.TV)
        with filing.to_nas():
            folder = self._archive.place(Path(row.path.parent), {row.path.name: src}, library)
        self.titles.set_status(rec.id, row.title_number, EncodeStatus.FILED)
        src.unlink(missing_ok=True)
        self._jobs.log(rec.id, f"Filed {row.path.name} to {folder}")

    def _finish(self, rec: JobRecord, rows: list[TvTitle]) -> None:
        series = rows[0].series
        n = sum(1 for r in rows if r.episode)
        # The show's folder, or the film's for an Extras Disc: `TV/<show>`, `Movies/<film>`
        show = self._archive.folder(Path(*rows[0].path.parts[:2]),
                                    self._library(rec, kind_of_path(rows[0].path)
                                                  or LibraryKind.TV))
        what = (f"{n} Episode{'s' if n != 1 else ''}" if n
                else f"{len(rows)} Extra{'s' if len(rows) != 1 else ''}")
        # An Extras Disc is filed as its film's Extras: keep the film, not the "series".
        film = n == 0 and rows[0].path.parts[0] == LibraryKind.FILMS.folder
        self._media.save(rec.id, screen(self._tmdb, self._covers, not film, series.id,
                                        series.name, series.year,
                                        lambda text: self._jobs.log(rec.id, text)))
        self._jobs.mark_filed(rec.id, f"{series.title} · {what}", show)
        self._jobs.log(rec.id, f"All kept Titles filed to {show}; scratch deleted")
        filing.scan(self._plex, self._jobs, rec.id, show)

    # -- for the UI ---------------------------------------------------------

    def filed(self, limit: int = 100) -> list[FiledTv]:
        recs = self._jobs.list(JobStatus.FILED, types=VIDEO_DISC_TYPES)[:limit]
        return [FiledTv(r, rows) for r in recs if (rows := self.titles.for_job(r.id))]

    def queue_view(self) -> dict[str, Any]:
        """For the Encoding bin: kept Titles not yet filed, and their Discs' Types."""
        rows = [r for r in self.titles.queue() if r.status != EncodeStatus.FILED]
        types = {r.job_id: rec.disc_type for r in rows if (rec := self._jobs.get(r.job_id))}
        return {"tv_encoding": rows, "tv_disc_types": types}

    def _publish(self) -> None:
        for topic in PIPELINE_TOPICS:
            self._bus.publish(topic)
