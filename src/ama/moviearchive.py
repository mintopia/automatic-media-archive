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
- Extras (#8): after the Main Feature, every other ripped Title is Encoded the
  same way (`extra_t<n>.mkv`) and filed with the film to its `Other/` folder
  (`extras.py`). An Extra whose Encode fails is left out; it never holds up the film.

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

from ama import decoys, encode, hdr, picture, review
from ama import extras as extras_mod
from ama.covers import Covers
from ama.media import MediaStore, screen
from ama.archive import Archive, FilingError, extended_path
from ama.archive import move as archive_move
from ama.config import CqConfig
from ama.db import Database
from ama.discs import DiscRecord, DiscStatus, DiscStore, ReviewReason, TitleRecord, TitleStatus
from ama.drive import DiscType
from ama.encode import EncodeProgress, ProgressReader
from ama.events import EventBus
from ama.extras import Category, Extras, ExtraStatus
from ama.nas import NasConnected, NasMonitor
from ama.plex import Plex
from ama.proc import Streamer
from ama.tmdb import Candidate, Series, Tmdb, TmdbError, decide, load_hints, \
    movie_file_stem, movie_folder, search_terms, title_matches
from ama.tools import ToolLookup, ToolUnavailable
from ama.tv import looks_like_tv, might_be_tv, series_terms
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
    name: str  # what is being encoded: "Arrival (2016)", "The Office - s01e04 - The Quiz"
    progress: EncodeProgress


@dataclass(frozen=True)
class FiledMovie:
    """A filed movie Disc, for the UI."""

    record: DiscRecord
    movie: Movie
    extras: int = 0  # Extras filed with it


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
                 clock: Callable[[], float] = time.monotonic,
                 claimed: Callable[[int], bool] = lambda disc_id: False, *,
                 extras: Extras, media: MediaStore, covers: Covers) -> None:
        self._media = media
        self._covers = covers
        self._discs = discs
        self.movies = movies
        self.extras = extras
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
        self._claimed = claimed  # Discs another stage files (TV, #13): not identified here
        self.current: EncodeJob | None = None
        self.encoder = asyncio.Lock()  # one Encode at a time, whoever asks (films, TV)
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
        self.extras.requeue_unfinished()

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
            if (self.movies.get(rec.id) is not None or self._claimed(rec.id)
                    or not self._due(key)):
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
        # TV is never accepted as a film, however well one fits.
        if looks_like_tv(rec.titles):
            self._to_tv_review(rec, "Several Titles are episode-length, so this looks like TV")
            return
        if not self._tmdb.configured:
            raise RetryLater("No TMDB API key is set in ama.toml ([tmdb] api_key)")
        hints = load_hints(rec.scratch_dir, rec.label)
        terms = search_terms(hints)
        try:
            candidates = self._tmdb.candidates(terms) if terms else []
            series = (self._series_named(series_terms(hints))
                      if might_be_tv(rec.titles) else None)
        except TmdbError as e:
            raise RetryLater(str(e)) from None
        (rec.scratch_dir / TMDB_FILE).write_text(json.dumps(
            {"terms": terms, "main_feature": main.number,
             "candidates": [c.to_json() for c in candidates]}, ensure_ascii=False),
            encoding="utf-8")
        film, reason = decide(candidates, main.duration_s)
        if film is None and series is not None:
            self._to_tv_review(rec, f"Two Titles are episode-length and TMDB knows the series "
                                    f"{series.title}, so this looks like TV")
            return
        searched = ", ".join(f"“{t}”" for t in terms) or "nothing (the Disc has no usable name)"
        found = decoys.detect(t for t in rec.titles if t.status == TitleStatus.RIPPED)
        if found is not None:
            likely = found.likely
            name = f"Title {likely.number}" + (f" ({likely.source})" if likely.source else "")
            self._discs.log(rec.id, f"Suspected decoy playlists: {len(found.versions)} Titles "
                                    f"run within {decoys.DURATION_TOLERANCE_S} s of each other; "
                                    + (f"{name} plays in order, likely the film"
                                       if found.confident else
                                       "none plays more in order than the others"))
            if film is not None:  # confident, but which Title is the film is for Review
                reason, film = ReviewReason.DECOY_PLAYLISTS, None
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

    def _to_tv_review(self, rec: DiscRecord, why: str) -> None:
        self._discs.mark_review(rec.id, ReviewReason.EPISODES)
        self._discs.log(rec.id, f"{why}. Needs Review: match the Titles to Episodes")

    def _series_named(self, terms: list[str]) -> Series | None:
        """The first TMDB series titled exactly like one of `terms`. Raises TmdbError."""
        for term in terms:
            for series in self._tmdb.search_tv(term, limit=3):
                if title_matches({"title": series.name}, term):
                    return series
        return None

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
                await self._encode_extras(rec, movie)
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
        ffmpeg, ffprobe = self.encode_tools()
        title = next(t for t in rec.titles if t.number == movie.title_number)
        self.movies.set_status(rec.id, EncodeStatus.ENCODING)
        movie = self.movies.get(rec.id) or movie
        height = await self.encode_title(rec, title, movie.film.name,
                                         movie.film.original_language,
                                         rec.scratch_dir / ENCODED, ffmpeg, ffprobe)
        if height is None:
            self.movies.set_status(rec.id, EncodeStatus.FAILED)
            return False
        self.movies.set_status(rec.id, EncodeStatus.ENCODED, video_height=height)
        return True

    async def _encode_extras(self, rec: DiscRecord, movie: Movie) -> None:
        """Encode each Extra not Encoded yet (#8). One that fails is left out, logged."""
        titles = extras_mod.extra_titles(rec.titles, movie.title_number)
        hints = load_hints(rec.scratch_dir, rec.label)
        self.extras.plan(rec.id, extras_mod.default_names(
            titles, (hints.disc_name, hints.volume_name, rec.label, movie.film.title),
            rec.label))
        by_number = {t.number: t for t in titles}
        for extra in self.extras.of(rec.id):
            title = by_number.get(extra.title_number)
            if title is None or extra.status not in (ExtraStatus.QUEUED, ExtraStatus.ENCODING):
                continue
            ffmpeg, ffprobe = self.encode_tools()
            self.extras.set_status(rec.id, extra.title_number, ExtraStatus.ENCODING)
            height = await self.encode_title(rec, title, extra.name,
                                             movie.film.original_language,
                                             rec.scratch_dir / extra.encoded, ffmpeg, ffprobe,
                                             extra=True)
            if height is None:
                self.extras.set_status(rec.id, extra.title_number, ExtraStatus.FAILED)
                continue
            self.extras.set_status(rec.id, extra.title_number, ExtraStatus.ENCODED)
            await self._take_stills(rec, title, ffmpeg)

    async def _take_stills(self, rec: DiscRecord, title: TitleRecord, ffmpeg: Path) -> None:
        """Stills of an Extra for the sorting page, kept after scratch is deleted."""
        from ama.moviereview import POSITIONS, thumb_args  # that module imports this one

        for pct in POSITIONS:
            dest = self.extras.still(rec.id, title.number, pct)
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(f"{dest.stem}.tmp.jpg")
            try:
                code = await asyncio.to_thread(
                    self._stream, thumb_args(ffmpeg, rec.scratch_dir / title.file,
                                             title.duration_s * pct / 100, tmp), lambda _: None)
            except OSError:
                code = -1
            if code == 0 and tmp.exists():
                tmp.replace(dest)
            else:
                tmp.unlink(missing_ok=True)

    def encode_tools(self) -> tuple[Path, Path]:
        """(ffmpeg, ffprobe); RetryLater while they aren't ready."""
        try:
            return self._tool("ffmpeg"), self._tool("ffprobe")
        except ToolUnavailable as e:
            raise RetryLater(f"{e.name} isn't ready yet") from None

    async def encode_title(self, rec: DiscRecord, title: TitleRecord, name: str,
                           original_language: str, done: Path, ffmpeg: Path, ffprobe: Path,
                           extra: bool = False) -> int | None:
        """Encode one ripped Title of `rec` to `done` (written as `<stem>.tmp.mkv`, then
        renamed), tagged `name`. Returns its picture height, or None if the Encode failed
        (logged; the Rip is kept). One Encode at a time across callers (`encoder`).
        `extra`: a film's Extra (#8), Encoded as what it is (a UHD's HD Extra gets BD's
        CQ) and left out if it fails."""
        async with self.encoder:
            return await self._encode_title(rec, title, name, original_language, done,
                                            ffmpeg, ffprobe, extra)

    async def _encode_title(self, rec: DiscRecord, title: TitleRecord, name: str,
                            original_language: str, done: Path, ffmpeg: Path, ffprobe: Path,
                            extra: bool) -> int | None:
        then = (f"The Extra “{name}” is left out; the film is filed without it" if extra
                else "The Rip is kept; the Encode will be tried again when the app restarts")
        src = rec.scratch_dir / title.file
        tmp = done.with_name(f"{done.stem}.tmp.mkv")
        self._abort = False
        self.current = EncodeJob(rec, name, EncodeProgress(0.0))
        self._publish()
        try:
            probe_lines: list[str] = []
            code = await asyncio.to_thread(self._stream, encode.ffprobe_args(ffprobe, src),
                                           probe_lines.append)
            try:
                probe = encode.parse_probe("\n".join(probe_lines))
                sel = encode.select_streams(probe, original_language)
            except ValueError as e:
                return self._failed(rec, then,f"Couldn't read Title {title.number} ({e}; ffprobe exit "
                                         f"{code})", probe_lines[-LOG_TAIL:])
            source_hdr = await self._probe_hdr(ffprobe, src)
            if isinstance(source_hdr, str):
                return self._failed(rec, then,f"Couldn't read the colour of Title {title.number} "
                                         f"({source_hdr})", [])
            kind = encode_disc_type(
                DiscType.BD if extra and rec.disc_type == DiscType.UHD else rec.disc_type,
                probe.height)
            if kind != rec.disc_type and not extra:
                self._discs.log(rec.id, f"The Disc looked like a {rec.disc_type.long_name}, but "
                                        f"its Main Feature is 4K, so it is encoded as a UHD")
            cq = encode.cq_for(self._cq, kind)
            pic = await self._analyse_picture(rec, ffmpeg, src, probe)
            self._discs.log(rec.id, pic.describe())
            self._discs.log(rec.id, f"Encoding Title {title.number} as {name}: HEVC "
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
                    self.current = EncodeJob(rec, name, p)
                    self._publish_soon()

            tmp.unlink(missing_ok=True)
            started = self._clock()
            args = encode.ffmpeg_args(ffmpeg, src, tmp, sel, cq, name,
                                      colour=source_hdr.colour if source_hdr.is_hdr10 else None,
                                      video_filter=pic.filters)
            try:
                code = await asyncio.to_thread(self._stream, args, on_line)
            except asyncio.CancelledError:
                self._abort = True  # kills ffmpeg; recover() requeues it next start
                raise
            except OSError as e:
                return self._failed(rec, then,f"ffmpeg couldn't be started ({e.strerror or e})", [])
            if code != 0 or not tmp.exists():
                tmp.unlink(missing_ok=True)
                return self._failed(rec, then,f"ffmpeg stopped with exit code {code}", list(tail))
            if source_hdr.is_hdr10:
                encoded_hdr = await self._probe_hdr(ffprobe, tmp)
                lost = ([f"ffprobe couldn't read it ({encoded_hdr})"]
                        if isinstance(encoded_hdr, str)
                        else hdr.differences(source_hdr, encoded_hdr))
                if lost:
                    tmp.unlink(missing_ok=True)
                    return self._failed(rec, then,"the Encode didn't keep the HDR10 metadata: "
                                             + "; ".join(lost), [])
                self._discs.log(rec.id, f"HDR10 metadata kept: {encoded_hdr}")
            os.replace(tmp, done)
            minutes = max(1, round((self._clock() - started) / 60))
            self._discs.log(rec.id, f"Encode{f' of the Extra “{name}”' if extra else ''} "
                                    f"finished in {minutes} min "
                                    f"({done.stat().st_size / 1000**3:.1f} GB)")
            return probe.height
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

    def _failed(self, rec: DiscRecord, then: str, why: str, tail: list[str]) -> None:
        for line in tail:
            self._discs.log(rec.id, line, error=True)
        self._discs.log(rec.id, f"The Encode didn't work: {why}. {then}", error=True)

    # -- filing -------------------------------------------------------------

    def file(self, rec: DiscRecord, movie: Movie) -> None:
        """File `encode.mkv` into the Archive, then delete the Disc's scratch and tell Plex."""
        if not isinstance(self._nas.status, NasConnected):
            raise RetryLater("The NAS isn't connected")
        version = plex_version(rec.disc_type, movie.video_height)
        name = f"{movie_file_stem(movie.film)}{f' - {version}' if version else ''}.mkv"
        rel = movie_folder(movie.film)
        try:
            folder = self._archive.place(rel, {name: rec.scratch_dir / ENCODED})
            extras = self._file_extras(rec, rel)
        except (OSError, FilingError) as e:
            raise RetryLater(f"Couldn't file to the NAS ({e})") from e
        film = movie.film
        self._media.save(rec.id, screen(self._tmdb, self._covers, False, film.id, film.title,
                                        film.year, lambda text: self._discs.log(rec.id, text)))
        self._discs.mark_filed(rec.id, movie.film.name, folder)
        self._discs.log(rec.id, f"Filed {name} to {folder}; scratch deleted")
        if extras:
            self._discs.log(rec.id, f"Filed {extras} Extra{'s' if extras != 1 else ''} to "
                                    f"{Category.OTHER.value}")
        try:
            self._discs.log(rec.id, self._plex.scan(folder))
        except httpx.HTTPError as e:
            self._discs.log(rec.id, f"Couldn't ask Plex to scan the folder ({e}); "
                                    "Plex will find it on its next scan", error=True)

    def _file_extras(self, rec: DiscRecord, rel: Path) -> int:
        """Put the Disc's Encoded Extras into the film's `Other/` folder; how many are filed.

        Each file name is chosen once and saved before copying, so a retry reuses it; a
        name another Disc of the film already uses gets a number.
        """
        film = self._archive.root / rel
        taken = {e.file.casefold() for e in self.extras.of(rec.id) if e.file}
        for e in self.extras.of(rec.id):
            if e.status == ExtraStatus.ENCODED and not e.file:
                file = extras_mod.file_name(
                    e.category, e.name,
                    lambda f: f.casefold() in taken or extended_path(film / f).exists())
                self.extras.place(rec.id, e.title_number, e.name, e.category, file)
                taken.add(file.casefold())
        for e in self.extras.of(rec.id):
            if e.status == ExtraStatus.ENCODED:
                sub = Path(e.file)
                self._archive.place(rel / sub.parent, {sub.name: rec.scratch_dir / e.encoded})
                self.extras.set_status(rec.id, e.title_number, ExtraStatus.FILED)
        return sum(e.status == ExtraStatus.FILED for e in self.extras.of(rec.id))

    def sort_extras(self, rec: DiscRecord, changes: dict[int, tuple[str, Category]]) -> int:
        """The user sorted a filed Disc's Extras ({Title: (name, category)}): move each
        changed one to its Plex folder and ask Plex to rescan; how many moved.

        Marks the Extras sorted (publish `review` after). Blocking: call in a thread.
        Raises RetryLater if the NAS can't be reached.
        """
        if not isinstance(self._nas.status, NasConnected) or rec.archive_dir is None:
            raise RetryLater("The NAS isn't connected")
        film = rec.archive_dir
        filed = {e.title_number: e for e in self.extras.of(rec.id)
                 if e.status == ExtraStatus.FILED}
        taken = {e.file.casefold() for e in filed.values()}
        moved = 0
        for number, (name, category) in changes.items():
            e = filed.get(number)
            name = " ".join(name.split()) or (e.name if e else "")
            if e is None or (name, category) == (e.name, e.category):
                continue
            taken.discard(e.file.casefold())
            file = extras_mod.file_name(
                category, name, lambda f: f.casefold() in taken or extended_path(film / f).exists())
            try:
                archive_move(film / e.file, film / file)
            except OSError as err:
                raise RetryLater(f"Couldn't move “{e.name}” on the NAS ({err})") from err
            self.extras.place(rec.id, number, name, category, file)
            taken.add(file.casefold())
            self._discs.log(rec.id, f"Extra “{e.name}” moved to {file}")
            moved += 1
        self.extras.mark_reviewed(rec.id)
        if moved:
            try:
                self._discs.log(rec.id, self._plex.scan(film))
            except httpx.HTTPError as err:
                self._discs.log(rec.id, f"Couldn't ask Plex to scan the folder ({err}); "
                                        "Plex will find it on its next scan", error=True)
        return moved

    # -- for the UI ---------------------------------------------------------

    def filed(self, limit: int = 100) -> list[FiledMovie]:
        recs = self._discs.list(DiscStatus.FILED, types=VIDEO_DISC_TYPES)[:limit]
        return [FiledMovie(r, m, sum(e.status == ExtraStatus.FILED
                                     for e in self.extras.of(r.id)))
                for r in recs if (m := self.movies.get(r.id))]

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
