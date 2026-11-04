"""Movie Identification, Encode and filing to the Archive (#6).

`MovieArchiver.run()` runs two loops side by side, both independent of Rips
(which run in their own task, so a Rip and an Encode overlap freely):

- Identification: each `ripped` video Disc with no Identification yet is searched
  on TMDB (`tmdb.py`) using the hints saved at Rip time and its Main Feature (the
  longest Title). A confident match joins the Encode queue (`movies` table); any
  other outcome leaves the Disc for Review with its reason, and the TMDB
  candidates are kept in scratch (`tmdb.json`) for Review to choose from.
- Encode: one at a time, oldest queued first. ffprobe picks the streams
  (`encode.py`), ffmpeg hevc_nvenc writes `encode.tmp.mkv`, renamed to
  `encode.mkv` on success. It is then filed as
  `Movies/Title (Year) {tmdb-ID}/Title (Year) {tmdb-ID}.mkv` (temp name ->
  rename, verified; `archive.py`), the Disc marked filed and its scratch (the
  lossless Rip, ADR-0002) deleted, and Plex asked to scan the folder.

Network/NAS trouble retries every `retry_seconds`. An Encode cut short by a
restart, or one that failed, is queued again at the next start; its Rip is kept.
"""

from __future__ import annotations

import asyncio
import collections
import json
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path

import httpx

from ama import encode, hdr, picture, review
from ama.archive import Archive, FilingError
from ama.config import CqConfig
from ama.db import Database
from ama.discs import DiscRecord, DiscStatus, DiscStore, ReviewReason, TitleRecord,     TitleStatus
from ama.drive import DiscType
from ama.encode import EncodeProgress, ProgressReader
from ama.events import EventBus
from ama.nas import NasConnected, NasMonitor
from ama.plex import Plex
from ama.proc import Streamer
from ama.tmdb import Candidate, Tmdb, TmdbError, decide, load_hints, movie_file_stem, \
    movie_folder, search_terms
from ama.tools import ToolLookup, ToolUnavailable
from ama.tv import looks_like_tv
from ama.video_rip import VIDEO_DISC_TYPES

log = logging.getLogger(__name__)

TOPIC = "encode"
TMDB_FILE = "tmdb.json"
ENCODE_TMP = "encode.tmp.mkv"
ENCODED = "encode.mkv"
PUBLISH_EVERY_SECONDS = 0.5
LOG_TAIL = 15  # ffmpeg warning lines kept for the Disc log when an Encode fails


class RetryLater(Exception):
    """Something outside AMA (TMDB, NAS, a tool) isn't available yet."""


class EncodeStatus(StrEnum):
    QUEUED = "queued"
    ENCODING = "encoding"
    ENCODED = "encoded"  # waiting to be filed
    FAILED = "failed"


@dataclass(frozen=True)
class Movie:
    """A video Disc Identified as a film, and its place in the Encode queue."""

    disc_id: int
    film: Candidate
    title_number: int  # the Main Feature
    status: EncodeStatus
    queued_at: datetime
    video_height: int = 0

    @property
    def resolution(self) -> str:
        return f"{self.video_height}p" if self.video_height else ""


class Movies:
    def __init__(self, db: Database, now: Callable[[], datetime] = datetime.now) -> None:
        self._db = db
        self._now = now

    _COLS = ("disc_id, tmdb_id, title, original_title, year, original_language, runtime_min, "
             "title_number, encode_status, queued_at, video_height")

    def _movie(self, row) -> Movie:
        (disc_id, tmdb_id, title, orig, year, lang, runtime, number, status, queued,
         height) = row
        return Movie(disc_id, Candidate(tmdb_id, title, orig, year, lang, runtime), number,
                     EncodeStatus(status), datetime.fromisoformat(queued), height)

    def enqueue(self, disc_id: int, film: Candidate, title_number: int) -> None:
        """Queue the Disc's Main Feature for Encode as `film` (idempotent; #7 calls this too)."""
        self._db.execute(
            f"INSERT INTO movies ({self._COLS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, 0) "
            "ON CONFLICT (disc_id) DO UPDATE SET tmdb_id = excluded.tmdb_id, "
            "title = excluded.title, original_title = excluded.original_title, "
            "year = excluded.year, original_language = excluded.original_language, "
            "runtime_min = excluded.runtime_min, title_number = excluded.title_number",
            (disc_id, film.id, film.title, film.original_title, film.year,
             film.original_language, film.runtime_min, title_number,
             self._now().isoformat(timespec="seconds")))

    def get(self, disc_id: int) -> Movie | None:
        row = self._db.execute(f"SELECT {self._COLS} FROM movies WHERE disc_id = ?",
                               (disc_id,)).fetchone()
        return self._movie(row) if row else None

    def queue(self) -> list[Movie]:
        """Movies not yet filed, first in first out."""
        rows = self._db.execute(
            f"SELECT {', '.join('m.' + c.strip() for c in self._COLS.split(','))} FROM movies m "
            "JOIN discs d ON d.id = m.disc_id WHERE d.status = 'ripped' "
            "ORDER BY m.queued_at, m.disc_id").fetchall()
        return [self._movie(r) for r in rows]

    def set_status(self, disc_id: int, status: EncodeStatus, video_height: int | None = None
                   ) -> None:
        self._db.execute("UPDATE movies SET encode_status = ?, "
                         "video_height = COALESCE(?, video_height) WHERE disc_id = ?",
                         (status.value, video_height, disc_id))

    def requeue_unfinished(self) -> list[int]:
        """At startup: Encodes cut short, or failed, go back in the queue (Rips are kept)."""
        rows = self._db.execute("SELECT disc_id FROM movies "
                                "WHERE encode_status IN ('encoding', 'failed')").fetchall()
        self._db.execute("UPDATE movies SET encode_status = 'queued' "
                         "WHERE encode_status IN ('encoding', 'failed')")
        return [r[0] for r in rows]


@dataclass(frozen=True)
class EncodeJob:
    """The Encode in progress (memory only), for the UI."""

    disc: DiscRecord
    movie: Movie
    progress: EncodeProgress


@dataclass(frozen=True)
class FiledMovie:
    """A filed movie Disc, for the UI."""

    record: DiscRecord
    movie: Movie


def main_feature(titles: tuple[TitleRecord, ...]) -> TitleRecord | None:
    """The Main Feature: the longest Title ripped (decoys/TV are Review's job, #7/#9)."""
    ripped = [t for t in titles if t.status == TitleStatus.RIPPED]
    return max(ripped, key=lambda t: (t.duration_s, -t.number), default=None)


UHD_MIN_HEIGHT = 1500  # taller than this is a 4K (UHD) picture, whatever the Disc looked like


def encode_disc_type(disc_type: DiscType, video_height: int) -> DiscType:
    """The Disc Type to Encode as: a 4K Main Feature is a UHD's (BD/UHD detection is a guess)."""
    return DiscType.UHD if video_height > UHD_MIN_HEIGHT else disc_type


def plex_version(disc_type: DiscType, video_height: int) -> str | None:
    """The Plex version name (`... - 4K.mkv`), so a film's BD and UHD share a folder (#11)."""
    if encode_disc_type(disc_type, video_height) == DiscType.UHD:
        return "4K"
    return "1080p" if disc_type == DiscType.BD else None


class _Aborted(Exception):
    pass


class MovieArchiver:
    TOPIC = TOPIC

    def __init__(self, discs: DiscStore, movies: Movies, tmdb: Tmdb, nas: NasMonitor,
                 archive: Archive, plex: Plex, bus: EventBus, cq: CqConfig, tool: ToolLookup,
                 streamer: Streamer, interval: float, retry_seconds: float = 60.0,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._discs = discs
        self.movies = movies
        self._tmdb = tmdb
        self._nas = nas
        self._archive = archive
        self._plex = plex
        self._bus = bus
        self._cq = cq
        self._tool = tool
        self._stream = streamer
        self._interval = interval
        self.retry_seconds = retry_seconds
        self._clock = clock
        self.current: EncodeJob | None = None
        self._not_before: dict[tuple[str, int], float] = {}
        self._warned: set[tuple[str, int]] = set()
        self._abort = False
        self._last_publish = 0.0
        self._loop: asyncio.AbstractEventLoop | None = None

    # -- lifecycle ----------------------------------------------------------

    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        self.recover()
        await asyncio.gather(self._every(self.identify_once), self._every(self.encode_once))

    async def _every(self, step: Callable[[], object]) -> None:
        while True:
            await step()  # type: ignore[misc]
            await asyncio.sleep(self._interval)

    def recover(self) -> None:
        for disc_id in self.movies.requeue_unfinished():
            self._discs.log(disc_id, "Encode queued again after a restart")

    def _due(self, key: tuple[str, int]) -> bool:
        return self._clock() >= self._not_before.get(key, 0.0)

    def _later(self, key: tuple[str, int], why: str) -> None:
        if key not in self._warned:  # log a stuck step once, not every minute
            self._discs.log(key[1], f"{why}; trying again in a while", error=True)
            self._warned.add(key)
        self._not_before[key] = self._clock() + self.retry_seconds

    def _done(self, key: tuple[str, int]) -> None:
        self._not_before.pop(key, None)
        self._warned.discard(key)

    # -- Identification -----------------------------------------------------

    async def identify_once(self) -> None:
        waiting = self._discs.list(DiscStatus.RIPPED, include_dismissed=True,
                                   types=VIDEO_DISC_TYPES)
        for rec in reversed(waiting):  # oldest first
            key = ("identify", rec.id)
            if self.movies.get(rec.id) is not None or not self._due(key):
                continue
            try:
                await asyncio.to_thread(self.identify, rec)
            except RetryLater as e:
                self._later(key, str(e))
            except Exception:
                log.exception("Movie Identification of Disc %s crashed", rec.id)
                self._later(key, "Identification went wrong (see the app's log file)")
            else:
                self._done(key)
            self._publish()

    def identify(self, rec: DiscRecord) -> None:
        main = main_feature(rec.titles)
        if main is None:
            raise RetryLater("No ripped Title to identify")
        if looks_like_tv(rec.titles):  # never accepted as a film, however well one fits
            self._discs.mark_review(rec.id, ReviewReason.EPISODES)
            self._discs.log(rec.id, "Several Titles are episode-length, so this looks like TV. "
                                    "Needs Review: match the Titles to Episodes")
            return
        if not self._tmdb.configured:
            raise RetryLater("No TMDB API key is set in ama.toml ([tmdb] api_key)")
        terms = search_terms(load_hints(rec.scratch_dir, rec.label))
        try:
            candidates = self._tmdb.candidates(terms) if terms else []
        except TmdbError as e:
            raise RetryLater(str(e)) from None
        (rec.scratch_dir / TMDB_FILE).write_text(json.dumps(
            {"terms": terms, "main_feature": main.number,
             "candidates": [c.to_json() for c in candidates]}, ensure_ascii=False),
            encoding="utf-8")
        film, reason = decide(candidates, main.duration_s)
        searched = ", ".join(f"“{t}”" for t in terms) or "nothing (the Disc has no usable name)"
        if film is None:
            assert reason is not None
            self._discs.mark_review(rec.id, reason)
            self._discs.log(rec.id, f"Searched TMDB for {searched}: {len(candidates)} "
                                    f"film{'s' if len(candidates) != 1 else ''} found. "
                                    f"Needs Review: {reason.value.replace('_', ' ')}")
            return
        self._discs.log(rec.id, f"Identified as {film.name} (TMDB {film.id}, {film.runtime_min} "
                                f"min; Main Feature is Title {main.number}, {main.duration})")
        self.movies.enqueue(rec.id, film, main.number)
        self._discs.log(rec.id, "Queued for Encode")

    # -- Encode -------------------------------------------------------------

    async def encode_once(self) -> None:
        """Encode (or file) the first Movie in the queue that can go now."""
        self._loop = asyncio.get_running_loop()
        for movie in self.movies.queue():
            key = ("encode", movie.disc_id)
            if movie.status == EncodeStatus.FAILED or not self._due(key):
                continue
            rec = self._discs.get(movie.disc_id)
            assert rec is not None
            try:
                if movie.status != EncodeStatus.ENCODED:
                    if not await self._encode(rec, movie):
                        return
                await asyncio.to_thread(self.file, rec, self.movies.get(movie.disc_id) or movie)
            except RetryLater as e:
                self._later(key, str(e))
                continue
            except Exception:
                log.exception("Encode/filing of Disc %s crashed", rec.id)
                self._later(key, "The Encode or filing went wrong (see the app's log file)")
                continue
            finally:
                self._publish()
            self._done(key)
            return  # one at a time; the next waits for the next pass

    async def _encode(self, rec: DiscRecord, movie: Movie) -> bool:
        """Run the Encode; True when `encode.mkv` is ready. Raises RetryLater for tools."""
        try:
            ffmpeg, ffprobe = self._tool("ffmpeg"), self._tool("ffprobe")
        except ToolUnavailable as e:
            raise RetryLater(f"{e.name} isn't ready yet") from None
        title = next(t for t in rec.titles if t.number == movie.title_number)
        src = rec.scratch_dir / title.file
        tmp, done = rec.scratch_dir / ENCODE_TMP, rec.scratch_dir / ENCODED
        self.movies.set_status(rec.id, EncodeStatus.ENCODING)
        movie = self.movies.get(rec.id) or movie
        self._abort = False
        self.current = EncodeJob(rec, movie, EncodeProgress(0.0))
        self._publish()
        try:
            probe_lines: list[str] = []
            code = await asyncio.to_thread(self._stream, encode.ffprobe_args(ffprobe, src),
                                           probe_lines.append)
            try:
                probe = encode.parse_probe("\n".join(probe_lines))
                sel = encode.select_streams(probe, movie.film.original_language)
            except ValueError as e:
                return self._failed(rec, f"Couldn't read the Main Feature ({e}; ffprobe exit "
                                         f"{code})", probe_lines[-LOG_TAIL:])
            source_hdr = await self._probe_hdr(ffprobe, src)
            if isinstance(source_hdr, str):
                return self._failed(rec, f"Couldn't read the Main Feature's colour ({source_hdr})",
                                    [])
            kind = encode_disc_type(rec.disc_type, probe.height)
            if kind != rec.disc_type:
                self._discs.log(rec.id, f"The Disc looked like a {rec.disc_type.long_name}, but "
                                        f"its Main Feature is 4K, so it is encoded as a UHD")
            cq = encode.cq_for(self._cq, kind)
            pic = await self._analyse_picture(rec, ffmpeg, src, probe)
            self._discs.log(rec.id, pic.describe())
            self._discs.log(rec.id, f"Encoding Title {title.number} as {movie.film.name}: HEVC "
                                    f"10-bit, CQ {cq}; keeping {len(sel.audio)} audio and "
                                    f"{len(sel.subtitles)} subtitle tracks, {probe.chapters} "
                                    "chapters")
            if source_hdr.is_hdr10:
                dropped = [n for n, on in (("Dolby Vision", source_hdr.dolby_vision),
                                           ("HDR10+", source_hdr.hdr10_plus)) if on]
                self._discs.log(rec.id, f"HDR10: {source_hdr}" + (
                    f"; {' and '.join(dropped)} metadata will be dropped (ADR-0003)"
                    if dropped else ""))
            reader = ProgressReader(probe.duration_s or title.duration_s)
            tail: collections.deque[str] = collections.deque(maxlen=LOG_TAIL)

            def on_line(line: str) -> None:
                if self._abort:
                    raise _Aborted
                if not reader.is_progress(line):
                    tail.append(line)
                    return
                p = reader.feed(line)
                if p is not None and self.current is not None:
                    self.current = EncodeJob(rec, movie, p)
                    self._publish_soon()

            tmp.unlink(missing_ok=True)
            started = self._clock()
            args = encode.ffmpeg_args(ffmpeg, src, tmp, sel, cq, movie.film.name,
                                      colour=source_hdr.colour if source_hdr.is_hdr10 else None,
                                      video_filter=pic.filters)
            try:
                code = await asyncio.to_thread(self._stream, args, on_line)
            except asyncio.CancelledError:
                self._abort = True  # kills ffmpeg; recover() requeues it next start
                raise
            except OSError as e:
                return self._failed(rec, f"ffmpeg couldn't be started ({e.strerror or e})", [])
            if code != 0 or not tmp.exists():
                tmp.unlink(missing_ok=True)
                return self._failed(rec, f"ffmpeg stopped with exit code {code}", list(tail))
            if source_hdr.is_hdr10:
                encoded_hdr = await self._probe_hdr(ffprobe, tmp)
                lost = ([f"ffprobe couldn't read it ({encoded_hdr})"]
                        if isinstance(encoded_hdr, str)
                        else hdr.differences(source_hdr, encoded_hdr))
                if lost:
                    tmp.unlink(missing_ok=True)
                    return self._failed(rec, "the Encode didn't keep the HDR10 metadata: "
                                             + "; ".join(lost), [])
                self._discs.log(rec.id, f"HDR10 metadata kept: {encoded_hdr}")
            os.replace(tmp, done)
            minutes = max(1, round((self._clock() - started) / 60))
            self.movies.set_status(rec.id, EncodeStatus.ENCODED, video_height=probe.height)
            self._discs.log(rec.id, f"Encode finished in {minutes} min "
                                    f"({done.stat().st_size / 1000**3:.1f} GB)")
            return True
        finally:
            self.current = None

    async def _analyse_picture(self, rec: DiscRecord, ffmpeg: Path, src: Path,
                               probe: encode.Probe) -> picture.Picture:
        """Sample the Main Feature for black bars and, on a DVD, its scan type (#10).

        A sample that fails just counts for nothing: the Encode then crops less,
        never more.
        """
        video = probe.video
        assert video is not None  # select_streams already insisted on one
        dvd = rec.disc_type == DiscType.DVD
        runs: list[list[str]] = []
        for at in picture.sample_times(probe.duration_s):
            lines: list[str] = []

            def on_line(line: str, lines: list[str] = lines) -> None:
                if self._abort:
                    raise _Aborted
                lines.append(line)

            try:
                await asyncio.to_thread(self._stream,
                                        picture.sample_args(ffmpeg, src, at, idet=dvd), on_line)
            except asyncio.CancelledError:
                self._abort = True
                raise
            except OSError:
                pass
            runs.append(lines)
        return picture.analyse(runs, width=video.width, height=video.height,
                               fps=video.frame_rate, detect_scan=dvd)


    async def _probe_hdr(self, ffprobe: Path, path: Path) -> hdr.HdrInfo | str:
        """The video's colour and HDR10 metadata, or why it couldn't be read."""
        lines: list[str] = []
        code = await asyncio.to_thread(self._stream, hdr.probe_args(ffprobe, path), lines.append)
        try:
            return hdr.parse_hdr("\n".join(lines))
        except ValueError as e:
            return f"{e}; ffprobe exit {code}"

    def _failed(self, rec: DiscRecord, why: str, tail: list[str]) -> bool:
        for line in tail:
            self._discs.log(rec.id, line, error=True)
        self._discs.log(rec.id, f"The Encode didn't work: {why}. The Rip is kept; the Encode "
                                "will be tried again when the app restarts", error=True)
        self.movies.set_status(rec.id, EncodeStatus.FAILED)
        return False

    # -- filing -------------------------------------------------------------

    def file(self, rec: DiscRecord, movie: Movie) -> None:
        """File `encode.mkv` into the Archive, then delete the Disc's scratch and tell Plex."""
        if not isinstance(self._nas.status, NasConnected):
            raise RetryLater("The NAS isn't connected")
        version = plex_version(rec.disc_type, movie.video_height)
        name = f"{movie_file_stem(movie.film)}{f' - {version}' if version else ''}.mkv"
        try:
            folder = self._archive.place(movie_folder(movie.film),
                                         {name: rec.scratch_dir / ENCODED})
        except (OSError, FilingError) as e:
            raise RetryLater(f"Couldn't file to the NAS ({e})") from e
        self._discs.mark_filed(rec.id, movie.film.name, folder)
        self._discs.log(rec.id, f"Filed {name} to {folder}; scratch deleted")
        try:
            self._discs.log(rec.id, self._plex.scan(folder))
        except httpx.HTTPError as e:
            self._discs.log(rec.id, f"Couldn't ask Plex to scan the folder ({e}); "
                                    "Plex will find it on its next scan", error=True)

    # -- for the UI ---------------------------------------------------------

    def filed(self, limit: int = 100) -> list[FiledMovie]:
        recs = self._discs.list(DiscStatus.FILED, types=VIDEO_DISC_TYPES)[:limit]
        return [FiledMovie(r, m) for r in recs if (m := self.movies.get(r.id))]

    def queue_view(self) -> dict:
        """The Encoding bin: the queue, the running Encode and who's next."""
        queue = self.movies.queue()
        next_up = next((m.disc_id for m in queue if m.status == EncodeStatus.QUEUED), None)
        types = {m.disc_id: rec.disc_type for m in queue if (rec := self._discs.get(m.disc_id))}
        return {"encoding": queue, "encode_job": self.current, "encode_next": next_up,
                "disc_types": types}

    # -- publishing ---------------------------------------------------------

    def _publish(self) -> None:
        self._last_publish = self._clock()
        for topic in (TOPIC, "rip", "filed", review.TOPIC):
            self._bus.publish(topic)

    def _publish_soon(self) -> None:
        """From the ffmpeg thread: publish on the loop, at most every PUBLISH_EVERY_SECONDS."""
        if self._clock() - self._last_publish < PUBLISH_EVERY_SECONDS or self._loop is None:
            return
        self._last_publish = self._clock()
        self._loop.call_soon_threadsafe(self._bus.publish, TOPIC)
