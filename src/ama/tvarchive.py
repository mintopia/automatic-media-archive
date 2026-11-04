"""TV Encode and filing (#13).

Review keeps some of a TV Disc's Titles (`tvreview`): each is an Episode or an
Extra, with where it goes in the Archive (`tv.episode_path` / `tv.extra_path`).
They are queued in `tv_titles`. `TvArchiver` encodes them one by one through the
movie pipeline's Encode (`MovieArchiver.encode_title`, which also keeps it to one
Encode at a time across films and TV) to scratch `tv/t<n>.mkv`, files each as soon
as it is encoded, and once every kept Title is filed marks the Disc filed (its
scratch, the lossless Rip, is deleted: ADR-0002) and asks Plex to scan the show.

Trouble outside AMA (NAS, tools) retries every `retry_seconds`. A failed Encode
keeps the Rip; it and any Encode cut short by a restart are queued again at the
next start.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath

import httpx

from ama import review
from ama.archive import Archive, FilingError
from ama.db import Database
from ama.discs import DiscRecord, DiscStatus, DiscStore
from ama.events import EventBus
from ama.moviearchive import TOPIC, MovieArchiver, RetryLater
from ama.nas import NasConnected, NasMonitor
from ama.plex import Plex
from ama.tmdb import Episode, Series
from ama.tv import episode_path, extra_path
from ama.tvreview import Kept
from ama.video_rip import VIDEO_DISC_TYPES

log = logging.getLogger(__name__)

ENCODES = "tv"  # scratch subfolder for the Encodes


class TvStatus(StrEnum):
    QUEUED = "queued"
    ENCODING = "encoding"
    ENCODED = "encoded"  # waiting to be filed
    FILED = "filed"
    FAILED = "failed"


@dataclass(frozen=True)
class TvTitle:
    """A kept Title of a TV Disc and its place in the Encode queue."""

    disc_id: int
    title_number: int
    series: Series
    episode: Episode | None  # None: an Extra
    path: PurePosixPath      # in the Archive
    status: TvStatus
    queued_at: datetime
    video_height: int = 0

    @property
    def name(self) -> str:
        """"The Office - s01e04 - The Quiz" (what the Encode is tagged and shown as)."""
        return self.path.stem


def planned(series: Series, rec: DiscRecord, kept: Iterable[Kept]
            ) -> list[tuple[int, Episode | None, PurePosixPath]]:
    """(Title, Episode or None for an Extra, Archive path) for each kept Title."""
    return [(k.title.number, k.episode,
             episode_path(series, k.episode) if k.episode
             else extra_path(series, rec.label, k.title.number)) for k in kept]


class TvTitles:
    def __init__(self, db: Database, now: Callable[[], datetime] = datetime.now) -> None:
        self._db = db
        self._now = now

    _COLS = ("disc_id, title_number, tmdb_id, series, year, original_language, season, "
             "episode, episode_name, path, encode_status, queued_at, video_height")

    def _row(self, row) -> TvTitle:
        (disc_id, number, tmdb_id, name, year, lang, season, episode, ep_name, path, status,
         queued, height) = row
        return TvTitle(disc_id, number, Series(tmdb_id, name, year, lang),
                       Episode(season, episode, ep_name) if season is not None else None,
                       PurePosixPath(path), TvStatus(status), datetime.fromisoformat(queued),
                       height)

    def enqueue(self, disc_id: int, series: Series,
                kept: Iterable[tuple[int, Episode | None, PurePosixPath]]) -> None:
        """Queue the Disc's kept Titles for Encode, replacing any earlier decision."""
        queued = self._now().isoformat(timespec="seconds")
        self._db.execute("DELETE FROM tv_titles WHERE disc_id = ?", (disc_id,))
        for number, ep, path in kept:
            self._db.execute(
                f"INSERT INTO tv_titles ({self._COLS}) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, 0)",
                (disc_id, number, series.id, series.name, series.year, series.original_language,
                 ep.season if ep else None, ep.number if ep else None, ep.name if ep else "",
                 path.as_posix(), queued))

    def has(self, disc_id: int) -> bool:
        return self._db.execute("SELECT 1 FROM tv_titles WHERE disc_id = ? LIMIT 1",
                                (disc_id,)).fetchone() is not None

    def for_disc(self, disc_id: int) -> list[TvTitle]:
        rows = self._db.execute(f"SELECT {self._COLS} FROM tv_titles WHERE disc_id = ? "
                                "ORDER BY title_number", (disc_id,)).fetchall()
        return [self._row(r) for r in rows]

    def in_season(self, series_id: int, season: int) -> list[TvTitle]:
        """Every Disc's Episodes of the series' season (a set's earlier Discs, #14)."""
        rows = self._db.execute(f"SELECT {self._COLS} FROM tv_titles WHERE tmdb_id = ? AND "
                                "season = ? AND path LIKE 'TV/%' ORDER BY episode",
                                (series_id, season)).fetchall()
        return [self._row(r) for r in rows]

    def queue(self) -> list[TvTitle]:
        """Kept Titles of Discs not yet filed, first in first out."""
        cols = ", ".join("t." + c.strip() for c in self._COLS.split(","))
        rows = self._db.execute(
            f"SELECT {cols} FROM tv_titles t JOIN discs d ON d.id = t.disc_id "
            "WHERE d.status = 'ripped' ORDER BY t.queued_at, t.disc_id, t.title_number"
        ).fetchall()
        return [self._row(r) for r in rows]

    def set_status(self, disc_id: int, number: int, status: TvStatus,
                   video_height: int | None = None) -> None:
        self._db.execute("UPDATE tv_titles SET encode_status = ?, "
                         "video_height = COALESCE(?, video_height) "
                         "WHERE disc_id = ? AND title_number = ?",
                         (status.value, video_height, disc_id, number))

    def requeue_unfinished(self) -> list[int]:
        """At startup: Encodes cut short, or failed, go back in the queue (Discs affected)."""
        rows = self._db.execute("SELECT DISTINCT disc_id FROM tv_titles "
                                "WHERE encode_status IN ('encoding', 'failed')").fetchall()
        self._db.execute("UPDATE tv_titles SET encode_status = 'queued' "
                         "WHERE encode_status IN ('encoding', 'failed')")
        return [r[0] for r in rows]


@dataclass(frozen=True)
class FiledTv:
    """A filed TV Disc, for the UI."""

    record: DiscRecord
    episodes: list[TvTitle]


def encoded_path(rec: DiscRecord, number: int) -> Path:
    return rec.scratch_dir / ENCODES / f"t{number}.mkv"


class TvArchiver:
    def __init__(self, discs: DiscStore, titles: TvTitles, encoder: MovieArchiver,
                 nas: NasMonitor, archive: Archive, plex: Plex, bus: EventBus, interval: float,
                 retry_seconds: float = 60.0, clock: Callable[[], float] = time.monotonic
                 ) -> None:
        self._discs = discs
        self.titles = titles
        self._encoder = encoder
        self._nas = nas
        self._archive = archive
        self._plex = plex
        self._bus = bus
        self._interval = interval
        self.retry_seconds = retry_seconds
        self._clock = clock
        self._not_before: dict[int, float] = {}
        self._warned: set[int] = set()

    async def run(self) -> None:
        self.recover()
        while True:
            await self.once()
            await asyncio.sleep(self._interval)

    def recover(self) -> None:
        for disc_id in self.titles.requeue_unfinished():
            self._discs.log(disc_id, "Episode Encodes queued again after a restart")

    async def once(self) -> None:
        discs = dict.fromkeys(t.disc_id for t in self.titles.queue())
        for disc_id in discs:
            if self._clock() < self._not_before.get(disc_id, 0.0):
                continue
            rec = self._discs.get(disc_id)
            assert rec is not None
            try:
                await self._advance(rec)
            except RetryLater as e:
                if disc_id not in self._warned:
                    self._discs.log(disc_id, f"{e}; trying again in a while", error=True)
                    self._warned.add(disc_id)
                self._not_before[disc_id] = self._clock() + self.retry_seconds
            except Exception:
                log.exception("TV Encode/filing of Disc %s crashed", disc_id)
                self._discs.log(disc_id, "The Encode or filing went wrong (see the app's log "
                                         "file); trying again in a while", error=True)
                self._not_before[disc_id] = self._clock() + self.retry_seconds
            else:
                self._not_before.pop(disc_id, None)
                self._warned.discard(disc_id)
            finally:
                self._publish()

    async def _advance(self, rec: DiscRecord) -> None:
        """Encode and file what's left of the Disc's kept Titles; file the Disc when done."""
        titles = {t.number: t for t in rec.titles}
        for row in self.titles.for_disc(rec.id):
            if row.status in (TvStatus.QUEUED, TvStatus.ENCODING):
                ffmpeg, ffprobe = self._encoder.encode_tools()
                out = encoded_path(rec, row.title_number)
                out.parent.mkdir(exist_ok=True)
                self.titles.set_status(rec.id, row.title_number, TvStatus.ENCODING)
                self._publish()
                height = await self._encoder.encode_title(
                    rec, titles[row.title_number], row.name, row.series.original_language,
                    out, ffmpeg, ffprobe)
                if height is None:
                    self.titles.set_status(rec.id, row.title_number, TvStatus.FAILED)
                    continue
                self.titles.set_status(rec.id, row.title_number, TvStatus.ENCODED, height)
                row = next(r for r in self.titles.for_disc(rec.id)
                           if r.title_number == row.title_number)
            if row.status == TvStatus.ENCODED:
                await asyncio.to_thread(self._file_one, rec, row)
        rows = self.titles.for_disc(rec.id)
        if rows and all(r.status == TvStatus.FILED for r in rows):
            await asyncio.to_thread(self._finish, rec, rows)

    def _file_one(self, rec: DiscRecord, row: TvTitle) -> None:
        if not isinstance(self._nas.status, NasConnected):
            raise RetryLater("The NAS isn't connected")
        src = encoded_path(rec, row.title_number)
        try:
            folder = self._archive.place(Path(row.path.parent), {row.path.name: src})
        except (OSError, FilingError) as e:
            raise RetryLater(f"Couldn't file to the NAS ({e})") from e
        self.titles.set_status(rec.id, row.title_number, TvStatus.FILED)
        src.unlink(missing_ok=True)
        self._discs.log(rec.id, f"Filed {row.path.name} to {folder}")

    def _finish(self, rec: DiscRecord, rows: list[TvTitle]) -> None:
        series = rows[0].series
        n = sum(1 for r in rows if r.episode)
        # The show's folder, or the film's for a bonus Disc (#14): `TV/<show>`, `Movies/<film>`
        show = self._archive.root / Path(*rows[0].path.parts[:2])
        what = (f"{n} Episode{'s' if n != 1 else ''}" if n
                else f"{len(rows)} Extra{'s' if len(rows) != 1 else ''}")
        self._discs.mark_filed(rec.id, f"{series.title} · {what}", show)
        self._discs.log(rec.id, f"All kept Titles filed to {show}; scratch deleted")
        try:
            self._discs.log(rec.id, self._plex.scan(show))
        except httpx.HTTPError as e:
            self._discs.log(rec.id, f"Couldn't ask Plex to scan the folder ({e}); "
                                    "Plex will find it on its next scan", error=True)

    # -- for the UI ---------------------------------------------------------

    def filed(self, limit: int = 100) -> list[FiledTv]:
        recs = self._discs.list(DiscStatus.FILED, types=VIDEO_DISC_TYPES)[:limit]
        return [FiledTv(r, rows) for r in recs if (rows := self.titles.for_disc(r.id))]

    def queue_view(self) -> dict:
        """For the Encoding bin: kept Titles not yet filed, and their Discs' Types."""
        rows = [r for r in self.titles.queue() if r.status != TvStatus.FILED]
        types = {r.disc_id: rec.disc_type for r in rows if (rec := self._discs.get(r.disc_id))}
        return {"tv_encoding": rows, "tv_disc_types": types}

    def _publish(self) -> None:
        for topic in (TOPIC, "rip", "filed", review.TOPIC):
            self._bus.publish(topic)
