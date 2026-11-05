"""Movie Identification, Encode and filing to the Archive.

`MovieArchiver.run()` runs two loops side by side, both independent of Rips:

- Identification: each `ripped` video Disc with no Identification yet is searched
  on TMDB using the hints saved at Rip time and its Main Feature (the longest
  Title). A confident match joins the Encode queue (`movies`), as does a film the user
  picked while it ripped (film_guess.py) whose runtime fits the Main Feature; any other outcome
  leaves the Disc for Review with its reason, and the TMDB candidates are kept in
  scratch (`tmdb.json`) for Review to choose from.
- Encode: one at a time, oldest queued first, through the shared `Encoder`; then
  every other ripped Title as an Extra (one that fails is left out). Filed to
  `Movies/Title (Year) {tmdb-ID}/` with its Extras under `Other/`; the Disc's
  scratch (the lossless Rip, ADR-0002) is deleted and Plex asked to scan.

An Encode cut short by a restart, or one that failed, is queued again at the next
start; its Rip is kept.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ama import decoys, filing
from ama import extras as extras_mod
from ama.archive import Archive, extended_path
from ama.archive import move as archive_move
from ama.covers import Covers
from ama.db import Database
from ama.jobs import JobRecord, JobStatus, JobStore, ReviewReason, TitleRecord, TitleStatus
from ama.drive import DiscType
from ama.encoder import PIPELINE_TOPICS, Encoder, EncodeQueue, EncodeStatus, encode_disc_type
from ama.events import EventBus
from ama.extras import Category, Extras, ExtraStatus
from ama.media import MediaStore, screen
from ama.nas import NasMonitor
from ama.plex import Plex
from ama.proc import Streamer
from ama.problems import Problem, Problems
from ama.retry import Backoff, RetryLater
from ama.tmdb import Candidate, Series, Tmdb, TmdbError, decide, decide_pick, load_hints, \
    movie_file_stem, movie_folder, search_terms, title_matches
from ama.tv import looks_like_tv, might_be_tv, series_terms
from ama.video_rip import VIDEO_DISC_TYPES

log = logging.getLogger(__name__)

TMDB_FILE = "tmdb.json"
ENCODE_TMP = "encode.tmp.mkv"
ENCODED = "encode.mkv"


@dataclass(frozen=True)
class Movie:
    """A video Disc Identified as a film, and its place in the Encode queue."""

    job_id: int
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
        self._queue = EncodeQueue(db, "movies", "encode_status")

    _COLS = ("job_id, tmdb_id, title, original_title, year, original_language, runtime_min, "
             "title_number, encode_status, queued_at, video_height")

    def _movie(self, row) -> Movie:
        (job_id, tmdb_id, title, orig, year, lang, runtime, number, status, queued,
         height) = row
        return Movie(job_id, Candidate(tmdb_id, title, orig, year, lang, runtime), number,
                     EncodeStatus(status), datetime.fromisoformat(queued), height)

    def enqueue(self, job_id: int, film: Candidate, title_number: int) -> None:
        """Queue the Disc's Main Feature for Encode as `film` (idempotent; Review calls it too)."""
        self._db.execute(
            f"INSERT INTO movies ({self._COLS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0) "
            "ON CONFLICT (job_id) DO UPDATE SET tmdb_id = excluded.tmdb_id, "
            "title = excluded.title, original_title = excluded.original_title, "
            "year = excluded.year, original_language = excluded.original_language, "
            "runtime_min = excluded.runtime_min, title_number = excluded.title_number",
            (job_id, film.id, film.title, film.original_title, film.year,
             film.original_language, film.runtime_min, title_number, EncodeStatus.QUEUED,
             self._now().isoformat(timespec="seconds")))

    def get(self, job_id: int) -> Movie | None:
        row = self._db.execute(f"SELECT {self._COLS} FROM movies WHERE job_id = ?",
                               (job_id,)).fetchone()
        return self._movie(row) if row else None

    def queue(self) -> list[Movie]:
        """Movies not yet filed, first in first out."""
        cols = ", ".join("q." + c.strip() for c in self._COLS.split(","))
        return [self._movie(r) for r in self._queue.waiting(cols, "q.queued_at, q.job_id")]

    def set_status(self, job_id: int, status: EncodeStatus, video_height: int | None = None
                   ) -> None:
        self._db.execute("UPDATE movies SET encode_status = ?, "
                         "video_height = COALESCE(?, video_height) WHERE job_id = ?",
                         (status.value, video_height, job_id))

    def requeue_unfinished(self) -> list[int]:
        """At startup: Encodes cut short, or failed, go back in the queue (Rips are kept)."""
        return self._queue.requeue(EncodeStatus.ENCODING, EncodeStatus.FAILED)


@dataclass(frozen=True)
class FiledMovie:
    """A filed movie Disc, for the UI."""

    record: JobRecord
    movie: Movie
    extras: int = 0  # Extras filed with it


def main_feature(titles: tuple[TitleRecord, ...]) -> TitleRecord | None:
    """The Main Feature: the longest Title ripped (decoys and TV are left to Review)."""
    ripped = [t for t in titles if t.status == TitleStatus.RIPPED]
    return max(ripped, key=lambda t: (t.duration_s, -t.number), default=None)


def plex_version(disc_type: DiscType, video_height: int) -> str | None:
    """The Plex version name (`... - 4K.mkv`), so a film's BD and UHD share a folder."""
    if encode_disc_type(disc_type, video_height) == DiscType.UHD:
        return "4K"
    return "1080p" if disc_type == DiscType.BD else None


class MovieArchiver:
    def __init__(self, jobs: JobStore, movies: Movies, tmdb: Tmdb, nas: NasMonitor,
                 archive: Archive, plex: Plex, bus: EventBus, encoder: Encoder,
                 streamer: Streamer, interval: float, retry_seconds: float = 60.0,
                 clock: Callable[[], float] = time.monotonic,
                 claimed: Callable[[int], bool] = lambda job_id: False, *,
                 extras: Extras, media: MediaStore, covers: Covers,
                 picked: Callable[[int], Candidate | None],
                 problems: Problems | None = None) -> None:
        self._media = media
        self._picked = picked  # the film the user picked while it ripped (film_guess.py)
        self._covers = covers
        self._jobs = jobs
        self.movies = movies
        self.extras = extras
        self._tmdb = tmdb
        self._nas = nas
        self._archive = archive
        self._plex = plex
        self._bus = bus
        self.encoder = encoder
        self._stream = streamer  # for Extras' stills
        self._interval = interval
        # keys are (step, Job id): Identification and Encode back off separately
        self.backoff = Backoff(retry_seconds, clock, problems, job=lambda key: key[1])
        self._claimed = claimed  # Discs another stage files (TV): not identified here

    # -- lifecycle ----------------------------------------------------------

    async def run(self) -> None:
        self.recover()
        await asyncio.gather(self._every(self.identify_once), self._every(self.encode_once))

    async def _every(self, step: Callable[[], Awaitable[object]]) -> None:
        while True:
            await step()
            await asyncio.sleep(self._interval)

    def recover(self) -> None:
        for job_id in self.movies.requeue_unfinished():
            self._jobs.log(job_id, "Encode queued again after a restart")
        self.extras.requeue_unfinished()

    def _later(self, key: tuple[str, int], why: str, problem: Problem | None = None) -> None:
        if self.backoff.later(key, why, problem):
            self._jobs.log(key[1], f"{why}; trying again in a while", error=True)

    # -- Identification -----------------------------------------------------

    async def identify_once(self) -> None:
        waiting = self._jobs.list(JobStatus.RIPPED, include_dismissed=True,
                                   types=VIDEO_DISC_TYPES)
        for rec in reversed(waiting):  # oldest first
            key = ("identify", rec.id)
            if (self.movies.get(rec.id) is not None or self._claimed(rec.id)
                    or not self.backoff.due(key)):
                continue
            try:
                await asyncio.to_thread(self.identify, rec)
            except RetryLater as e:
                self._later(key, str(e), e.problem)
            except Exception:
                log.exception("Movie Identification of Job %s crashed", rec.id)
                self._later(key, "Identification went wrong (see the app's log file)")
            else:
                self.backoff.done(key)
            self._publish()

    def identify(self, rec: JobRecord) -> None:
        main = main_feature(rec.titles)
        if main is None:
            raise RetryLater("No ripped Title to identify")
        # TV is never accepted as a film, however well one fits.
        if looks_like_tv(rec.titles):
            self._to_tv_review(rec, "Several Titles are episode-length, so this looks like TV")
            return
        if not self._tmdb.configured:
            raise RetryLater("No TMDB API key is set in ama.toml ([tmdb] api_key)",
                             Problem.TMDB_KEY)
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
        pick = self._picked(rec.id)
        film, reason = (decide_pick(pick, main.duration_s) if pick is not None
                        else decide(candidates, main.duration_s))
        if film is None and series is not None:
            self._to_tv_review(rec, f"Two Titles are episode-length and TMDB knows the series "
                                    f"{series.title}, so this looks like TV")
            return
        searched = ", ".join(f"“{t}”" for t in terms) or "nothing (the Disc has no usable name)"
        found = decoys.detect(t for t in rec.titles if t.status == TitleStatus.RIPPED)
        if found is not None:
            likely = found.likely
            name = f"Title {likely.number}" + (f" ({likely.source})" if likely.source else "")
            self._jobs.log(rec.id, f"Suspected decoy playlists: {len(found.versions)} Titles "
                                    f"run within {decoys.DURATION_TOLERANCE_S} s of each other; "
                                    + (f"{name} plays in order, likely the film"
                                       if found.confident else
                                       "none plays more in order than the others"))
            if film is not None:  # confident, but which Title is the film is for Review
                reason, film = ReviewReason.DECOY_PLAYLISTS, None
        if film is None:
            assert reason is not None
            self._jobs.mark_review(rec.id, reason)
            found_text = (f"Picked while it ripped: {pick.name} ({pick.runtime_min or '?'} min; "
                          f"Main Feature is Title {main.number}, {main.duration})"
                          if pick is not None else
                          f"Searched TMDB for {searched}: {len(candidates)} "
                          f"film{'s' if len(candidates) != 1 else ''} found")
            self._jobs.log(rec.id, f"{found_text}. Needs Review: "
                                    f"{reason.value.replace('_', ' ')}")
            return
        mine = "your pick, " if pick is not None else ""
        self._jobs.log(rec.id, f"Identified as {film.name} ({mine}TMDB {film.id}, "
                                f"{film.runtime_min} min; Main Feature is Title {main.number}, "
                                f"{main.duration})")
        self.movies.enqueue(rec.id, film, main.number)
        self._jobs.log(rec.id, "Queued for Encode")

    def _to_tv_review(self, rec: JobRecord, why: str) -> None:
        self._jobs.mark_review(rec.id, ReviewReason.EPISODES)
        self._jobs.log(rec.id, f"{why}. Needs Review: match the Titles to Episodes")

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
        for movie in self.movies.queue():
            key = ("encode", movie.job_id)
            if movie.status == EncodeStatus.FAILED or not self.backoff.due(key):
                continue
            rec = self._jobs.get(movie.job_id)
            assert rec is not None
            try:
                if movie.status != EncodeStatus.ENCODED:
                    if not await self._encode(rec, movie):
                        return
                await self._encode_extras(rec, movie)
                await asyncio.to_thread(self.file, rec, self.movies.get(movie.job_id) or movie)
            except RetryLater as e:
                self._later(key, str(e), e.problem)
                continue
            except Exception:
                log.exception("Encode/filing of Job %s crashed", rec.id)
                self._later(key, "The Encode or filing went wrong (see the app's log file)")
                continue
            finally:
                self._publish()
            self.backoff.done(key)
            return  # one at a time; the next waits for the next pass

    async def _encode(self, rec: JobRecord, movie: Movie) -> bool:
        """Run the Encode; True when `encode.mkv` is ready. Raises RetryLater for tools."""
        ffmpeg, ffprobe = self.encoder.tools()
        title = next(t for t in rec.titles if t.number == movie.title_number)
        self.movies.set_status(rec.id, EncodeStatus.ENCODING)
        movie = self.movies.get(rec.id) or movie
        height = await self.encoder.encode_title(rec, title, movie.film.name,
                                         movie.film.original_language,
                                         rec.scratch_dir / ENCODED, ffmpeg, ffprobe)
        if height is None:
            self.movies.set_status(rec.id, EncodeStatus.FAILED)
            return False
        self.movies.set_status(rec.id, EncodeStatus.ENCODED, video_height=height)
        return True

    async def _encode_extras(self, rec: JobRecord, movie: Movie) -> None:
        """Encode each Extra not Encoded yet. One that fails is left out, logged."""
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
            ffmpeg, ffprobe = self.encoder.tools()
            self.extras.set_status(rec.id, extra.title_number, ExtraStatus.ENCODING)
            height = await self.encoder.encode_title(rec, title, extra.name,
                                             movie.film.original_language,
                                             rec.scratch_dir / extra.encoded, ffmpeg, ffprobe,
                                             extra=True)
            if height is None:
                self.extras.set_status(rec.id, extra.title_number, ExtraStatus.FAILED)
                continue
            self.extras.set_status(rec.id, extra.title_number, ExtraStatus.ENCODED)
            await self._take_stills(rec, title, ffmpeg)

    async def _take_stills(self, rec: JobRecord, title: TitleRecord, ffmpeg: Path) -> None:
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

    # -- filing -------------------------------------------------------------

    def file(self, rec: JobRecord, movie: Movie) -> None:
        """File `encode.mkv` into the Archive, then delete the Job's scratch and tell Plex."""
        filing.require_nas(self._nas)
        version = plex_version(rec.disc_type, movie.video_height)
        name = f"{movie_file_stem(movie.film)}{f' - {version}' if version else ''}.mkv"
        rel = movie_folder(movie.film)
        with filing.to_nas():
            folder = self._archive.place(rel, {name: rec.scratch_dir / ENCODED})
            extras = self._file_extras(rec, rel)
        film = movie.film
        self._media.save(rec.id, screen(self._tmdb, self._covers, False, film.id, film.title,
                                        film.year, lambda text: self._jobs.log(rec.id, text)))
        self._jobs.mark_filed(rec.id, movie.film.name, folder)
        self._jobs.log(rec.id, f"Filed {name} to {folder}; scratch deleted")
        if extras:
            self._jobs.log(rec.id, f"Filed {extras} Extra{'s' if extras != 1 else ''} to "
                                    f"{Category.OTHER.value}")
        filing.scan(self._plex, self._jobs, rec.id, folder)

    def _file_extras(self, rec: JobRecord, rel: Path) -> int:
        """Put the Disc's Encoded Extras into the film's `Other/` folder; how many are filed.
        Each name is saved before copying so a retry reuses it."""
        film = self._archive.folder(rel)
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

    def sort_extras(self, rec: JobRecord, changes: dict[int, tuple[str, Category]]) -> int:
        """Move each Extra the user re-sorted ({Title: (name, category)}) to its Plex folder
        and mark the Disc's Extras sorted; how many moved. Blocking: call in a thread."""
        filing.require_nas(self._nas)
        if rec.archive_dir is None:
            raise RetryLater("The Disc has no folder in the Archive")
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
            self._jobs.log(rec.id, f"Extra “{e.name}” moved to {file}")
            moved += 1
        self.extras.mark_reviewed(rec.id)
        if moved:
            filing.scan(self._plex, self._jobs, rec.id, film)
        return moved

    # -- for the UI ---------------------------------------------------------

    def filed(self, limit: int = 100) -> list[FiledMovie]:
        recs = self._jobs.list(JobStatus.FILED, types=VIDEO_DISC_TYPES)[:limit]
        return [FiledMovie(r, m, sum(e.status == ExtraStatus.FILED
                                     for e in self.extras.of(r.id)))
                for r in recs if (m := self.movies.get(r.id))]

    def queue_view(self) -> dict[str, Any]:
        """The Encoding bin: the queue, the running Encode and who's next."""
        queue = self.movies.queue()
        next_up = next((m.job_id for m in queue if m.status == EncodeStatus.QUEUED), None)
        types = {m.job_id: rec.disc_type for m in queue if (rec := self._jobs.get(m.job_id))}
        return {"encoding": queue, "title_encode": self.encoder.current, "encode_next": next_up,
                "disc_types": types}

    # -- publishing ---------------------------------------------------------

    def _publish(self) -> None:
        for topic in PIPELINE_TOPICS:
            self._bus.publish(topic)
