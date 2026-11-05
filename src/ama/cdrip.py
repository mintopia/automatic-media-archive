"""CD Rip: an inserted Audio CD is Ripped by cyanrip to scratch, then ejected.

`CdRipper.run()` watches the drive. When a Disc arrives it first reads the TOC
(`cyanrip -I`), which also catches enhanced CDs that Windows only shows as a
data Disc. If there are audio tracks it Rips them to `scratch/cd/<Job id>/`
(per-track FLAC, `rip.cue`, `rip.log`), recording per-track AccurateRip results,
and ejects the Disc whatever happened. A failed Rip is recorded with its log,
its partial files are deleted and it is not retried: the user re-inserts.

Live state (`current`) is published on the `rip` topic; everything that must
survive a restart is in the `jobs`/`job_log`/`cd_tracks` tables.
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from ama import cyanrip
from ama.config import CdConfig
from ama.cyanrip import ArResult, ArStatus, Report
from ama.db import Database
from ama.jobs import JobRecord, JobStatus, JobStore, Failure, FailureKind
from ama.drive import DiscPresent, DiscType, DriveMonitor, UnrecognisedDisc
from ama.events import EventBus, Topic
from ama.pause import Pause
from ama.proc import Streamer
from ama.repeat import RepeatGuard, cd_fingerprint
from ama.scratch import ScratchGate
from ama.tools import ToolLookup, ToolUnavailable

if TYPE_CHECKING:
    from ama.cdguess import CdPick, CdPicks, Guess, Guesser
    from ama.media import Album
    from ama.musicbrainz import Match

log = logging.getLogger(__name__)


class _Stopped(Exception):
    """Raised from a cyanrip output line to stop it: AMA is shutting down."""


SCRATCH_SUBDIR = "cd"


@dataclass
class Track:
    number: int           # 0 = hidden track before track 1
    seconds: float
    preemphasis: bool = False
    ripped: bool = False
    percent: float = 0.0  # while ripping
    ar: ArResult | None = None


@dataclass
class CdRip:
    """A CD Rip in progress, as the UI shows it."""

    job_id: int
    label: str
    tracks: list[Track]
    current: int | None = None       # track number being ripped
    eta_seconds: int | None = None   # whole Disc
    mb_disc_id: str = ""             # MusicBrainz Disc ID, from the TOC
    guess: Guess | None = None       # likely or picked release while it rips (cdguess.py)

    def track_title(self, number: int) -> str | None:
        return self.guess.track_title(number) if self.guess else None

    @property
    def total_seconds(self) -> float:
        return sum(t.seconds for t in self.tracks)

    @property
    def percent(self) -> float:
        total = self.total_seconds
        if not total:
            return 0.0
        done = sum(t.seconds * (1.0 if t.ripped else t.percent / 100) for t in self.tracks)
        return min(100.0, 100 * done / total)

    def position(self) -> str:
        """Where the Rip is, e.g. "Track 5 of 12" (the hidden track 0 isn't counted)."""
        numbered = sum(1 for t in self.tracks if t.number > 0)
        if self.current == 0:
            return "Hidden track"
        current = self.current or next((t.number for t in self.tracks if not t.ripped), 1)
        return f"Track {current} of {numbered}"

    @property
    def hidden_track(self) -> Track | None:
        return next((t for t in self.tracks if t.number == 0), None)

    @property
    def preemphasis(self) -> bool:
        return any(t.preemphasis for t in self.tracks)


@dataclass
class CdJob:
    """A finished (or failed) CD record with its tracks, for the UI."""

    record: JobRecord
    tracks: list[Track] = field(default_factory=list)
    album: Album | None = None  # what it was filed as (media.py), once filed
    pick: CdPick | None = None  # the release the user picked while it ripped (cdguess.py)
    picked_titles: dict[int, str] = field(default_factory=dict)  # that release's, by track

    @property
    def name(self) -> str:
        """The picked album, else the Disc's label."""
        return self.pick.name if self.pick else (self.record.label or "Unknown CD")

    def track_title(self, number: int) -> str | None:
        return self.album.track_title(number) if self.album else self.picked_titles.get(number)

    @property
    def hidden_track(self) -> Track | None:
        return next((t for t in self.tracks if t.number == 0), None)

    @property
    def preemphasis(self) -> bool:
        return any(t.preemphasis for t in self.tracks)

    @property
    def total_seconds(self) -> float:
        return sum(t.seconds for t in self.tracks)

    @property
    def accuraterip(self) -> str:
        """The Rip's AccurateRip outcome in a few words, for History."""
        statuses = [t.ar.status if t.ar else ArStatus.UNAVAILABLE for t in self.tracks]
        if statuses and all(s == ArStatus.ACCURATE for s in statuses):
            return "verified"
        if bad := statuses.count(ArStatus.MISMATCH):
            return f"accepted with {bad} track{'s' if bad != 1 else ''} not matching"
        if ArStatus.NOT_IN_DB in statuses:
            return "not in AccurateRip"
        return "AccurateRip unavailable"


class CdTracks:
    """The `cd_tracks` table."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def save(self, job_id: int, tracks: list[Track]) -> None:
        for t in tracks:
            self._db.execute(
                "INSERT INTO cd_tracks (job_id, number, seconds, preemphasis, ripped, "
                "ar_status, ar_confidence) VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(job_id, number) DO UPDATE SET seconds = excluded.seconds, "
                "preemphasis = excluded.preemphasis, ripped = excluded.ripped, "
                "ar_status = excluded.ar_status, ar_confidence = excluded.ar_confidence",
                (job_id, t.number, t.seconds, int(t.preemphasis), int(t.ripped),
                 t.ar.status.value if t.ar else None, t.ar.confidence if t.ar else None))

    def load(self, job_id: int) -> list[Track]:
        rows = self._db.execute(
            "SELECT number, seconds, preemphasis, ripped, ar_status, ar_confidence "
            "FROM cd_tracks WHERE job_id = ? ORDER BY number", (job_id,)).fetchall()
        return [Track(n, s, bool(p), bool(r), 100.0 if r else 0.0,
                      ArResult(ArStatus(a), c) if a else None)
                for n, s, p, r, a, c in rows]


class NotRipping(Exception):
    """That Job's CD isn't the one ripping."""


class NotOffered(Exception):
    """That release isn't one of those that fit the CD being ripped."""


# ---- failures ---------------------------------------------------------------

def _f(kind: FailureKind, headline: str, advice: str) -> Failure:
    return Failure(kind, headline, advice)


NOT_INSTALLED = _f(FailureKind.NOT_INSTALLED, "cyanrip isn't installed.",
                   "Install cyanrip, set cd.cyanrip in ama.toml, restart AMA and insert the "
                   "Disc again.")
NO_AUDIO = _f(FailureKind.NO_AUDIO, "There are no audio tracks on this CD.",
              "Check it's an Audio CD. Nothing else on it can be archived.")
DRIVE = _f(FailureKind.DRIVE, "cyanrip couldn't read the drive.",
           "Check the drive is connected, then insert the Disc again.")
INTERRUPTED = _f(FailureKind.INTERRUPTED, "AMA stopped while this CD was ripping.",
                 "Insert the Disc again to rip it from the start.")
GENERIC = _f(FailureKind.RIP_ERROR, "The Rip stopped before it finished.",
             "Insert the Disc again to try once more. If it fails again, the log below says why.")


def _unreadable(track: int, retries: int) -> Failure:
    return _f(FailureKind.UNREADABLE_TRACK,
              f"Track {track} couldn't be read cleanly, even after {retries} tries.",
              "This usually means a scratch or smudge. Clean the Disc and insert it again. "
              "If it fails a second time, the Disc may be damaged.")


_DRIVE_ERRORS = re.compile(r"Unable to (?:init cdio context|open device)|cdio error", re.I)
_ERROR_LINE = re.compile(r"error|failed|unable|stopping|couldn't", re.I)


def is_error_line(text: str) -> bool:
    return bool(_ERROR_LINE.search(text)) and not re.match(r"^\s*(Ripping errors: 0|C2 errors)", text)


def strip_data_tracks(cue: str) -> str:
    """Drop enhanced-CD data tracks (`FILE "…" BINARY` + its TRACK) from a cue sheet:
    with `-X` cyanrip skips them but still lists them, pointing at a .bin it never wrote."""
    out: list[str] = []
    skipping = False
    for line in cue.splitlines(keepends=True):
        s = line.strip()
        if s.startswith("FILE "):
            skipping = s.endswith(" BINARY")
        elif s.startswith("TRACK ") and "MODE" in s:
            skipping = True
        elif s.startswith("TRACK "):
            skipping = False
        if not skipping:
            out.append(line)
    return "".join(out)


def tracks_from_info(report: Report) -> list[Track]:
    return [Track(t.number, t.seconds, t.preemphasis) for t in report.audio_tracks]


# ---- the worker -------------------------------------------------------------

class CdRipper:
    PUBLISH_EVERY = 0.5  # seconds between progress pushes to the UI

    def __init__(self, cfg: CdConfig, drive: DriveMonitor, jobs: JobStore, tracks: CdTracks,
                 bus: EventBus, streamer: Streamer, tool: ToolLookup, interval: float,
                 repeat: RepeatGuard, scratch: ScratchGate, pause: Pause, picks: CdPicks,
                 guesser: Guesser | None = None,
                 hold: Callable[[], bool] = lambda: False,
                 rip_settings: Callable[[JobRecord], CdConfig] | None = None) -> None:
        self._pause = pause
        # A Job's Rip settings, locked as its Rip starts (job_settings); else `cfg`.
        self._rip_settings = rip_settings or (lambda rec: self.cfg)
        self.picks = picks
        self.cfg = cfg
        self._hold = hold  # start no new Rip (a restart is waiting)
        self._guesser = guesser
        self.guess_retry_seconds = 60.0  # MusicBrainz trouble during the early guess
        self._repeat = repeat
        self._scratch = scratch
        self._tool = tool
        self._drive = drive
        self._jobs = jobs
        self._tracks = tracks
        self._bus = bus
        self._stream = streamer
        self._interval = interval
        self.current: CdRip | None = None
        self.reading_toc = False
        self.last_job_id: int | None = None
        self._handled: int | None = None  # the `DriveMonitor.insertion` already dealt with

    # -- queries for the UI --
    def job(self, job_id: int) -> CdJob | None:
        rec = self._jobs.get(job_id)
        if rec is None or rec.disc_type != DiscType.CD:
            return None
        return CdJob(rec, self._tracks.load(job_id), pick=self.picks.get(job_id))

    def jobs(self, status: JobStatus, limit: int = 10) -> list[CdJob]:
        """Recent CD records in `status` (not dismissed), newest first."""
        recs = [r for r in self._jobs.list(status) if r.disc_type == DiscType.CD][:limit]
        return [CdJob(r, self._tracks.load(r.id), pick=self.picks.get(r.id)) for r in recs]

    async def cover(self, match: Match) -> str | None:
        """A release's cached front cover, fetched if need be (None: none, or unreachable)."""
        return await self._guesser.cover(match) if self._guesser else None

    async def pick(self, job_id: int, release: str) -> CdPick:
        """The user picks `release` ("<release id>:<disc number>") for the CD being ripped: the
        rip card shows it at once (album, tracks, cover) and the Job keeps it."""
        live = self.current
        if live is None or live.job_id != job_id or self._guesser is None:
            raise NotRipping(job_id)
        pick = await self._guesser.pick(live, release)
        if pick is None:
            raise NotOffered(release)
        self.picks.save(job_id, pick)
        self._jobs.log(job_id, f"Picked {pick.album} by {pick.artist} (MusicBrainz release "
                               f"{pick.release_id}, disc {pick.disc_number})")
        self._publish()
        return pick

    # -- lifecycle --
    def recover(self) -> None:
        """A CD Rip still `ripping` at startup was cut off by a restart: fail it."""
        for rec in self._jobs.list(JobStatus.RIPPING, include_dismissed=True):
            if rec.disc_type == DiscType.CD:
                self._jobs.log(rec.id, "AMA restarted during the Rip", error=True)
                self._jobs.mark_failed(rec.id, INTERRUPTED)
                self._jobs.log(rec.id, "Removed partial files from scratch")

    async def run(self) -> None:
        await asyncio.to_thread(self.recover)
        while True:
            await self.check_once()
            await asyncio.sleep(self._interval)

    async def check_once(self) -> None:
        state = self._drive.state
        candidate = (isinstance(state, DiscPresent) and state.disc_type == DiscType.CD) \
            or isinstance(state, UnrecognisedDisc)
        if (not candidate or self._handled == self._drive.insertion or self._pause.paused
                or self._hold()):
            return
        try:
            self._tool("cyanrip")
        except ToolUnavailable:
            return  # wait in the drive until cyanrip is in; the Now page says why
        self._handled = self._drive.insertion
        try:
            await self.rip(state.label, known_cd=isinstance(state, DiscPresent))
        except Exception:
            log.exception("CD Rip crashed")
            self.current = None
            self._publish()

    def _publish(self) -> None:
        self._bus.publish(Topic.RIP)
        self._bus.publish(Topic.DRIVE)

    async def _eject(self, job_id: int | None) -> None:
        try:
            await self._drive.eject()
            if job_id is not None:
                self._jobs.log(job_id, "Disc ejected")
        except Exception as e:
            log.warning("eject failed: %s", e)
            if job_id is not None:
                self._jobs.log(job_id, f"Couldn't eject the Disc: {e}", error=True)

    async def _run_tool(self, args: list[str], on_line, cwd: Path | None = None) -> int:
        stopped = threading.Event()

        def line(ln: str) -> None:
            if stopped.is_set():
                raise _Stopped  # proc.stream kills cyanrip on the way out
            on_line(ln)

        try:
            return await asyncio.to_thread(self._stream, args, line, cwd)
        except asyncio.CancelledError:  # AMA is stopping: don't leave cyanrip ripping
            stopped.set()
            raise

    async def rip(self, label: str, known_cd: bool) -> None:
        device = self._drive.device() or "D:"
        exe = self._tool("cyanrip")

        # 1. TOC.
        self.reading_toc = known_cd
        self._publish()
        info_lines: list[str] = []
        try:
            code = await self._run_tool(cyanrip.info_command(exe, device, self.cfg.offset),
                                        info_lines.append)
        except FileNotFoundError:
            code = None
        finally:
            self.reading_toc = False
        info = cyanrip.parse_report("\n".join(info_lines))
        tracks = tracks_from_info(info) if code == 0 else []
        if not tracks and not known_cd:
            self._publish()
            return  # a data Disc, not an enhanced CD: not ours
        # A known CD waits for the user first; one they want again still needs room.
        fingerprint = cd_fingerprint(info.mb_disc_id) if tracks else None
        if not await self._repeat.admit(DiscType.CD, fingerprint):
            return
        if tracks and await self._scratch.refuses(DiscType.CD, label):  # ejected unripped
            self._publish()
            return
        rec = self._jobs.create(DiscType.CD, label, SCRATCH_SUBDIR)
        self._repeat.remember(rec.id, fingerprint)
        self.last_job_id = rec.id
        for ln in info_lines:
            self._jobs.log(rec.id, ln, error=is_error_line(ln))
        if not tracks:
            failure = NOT_INSTALLED if code is None else \
                DRIVE if any(_DRIVE_ERRORS.search(ln) for ln in info_lines) else NO_AUDIO
            await self._fail(rec, failure)
            return
        self._tracks.save(rec.id, tracks)
        self.current = CdRip(rec.id, label, tracks, mb_disc_id=info.mb_disc_id or "")
        self._publish()
        guessing = asyncio.create_task(self._guesser.follow(
            self.current, info.mcn, self._publish, lambda: self.guess_retry_seconds))             if self._guesser and info.mb_disc_id else None
        try:
            await self._rip(rec, exe, device, tracks)
        finally:
            if guessing:
                guessing.cancel()

    async def _rip(self, rec: JobRecord, exe: Path, device: str, tracks: list[Track]) -> None:

        # 2. Rip.
        cfg = self._rip_settings(rec)
        rec.scratch_dir.mkdir(parents=True, exist_ok=True)
        loop = asyncio.get_running_loop()
        rip_lines: list[str] = []
        errors_in: dict[int, int] = {}
        last_push = 0.0
        live = self.current

        pending = False

        def on_line(line: str) -> None:
            nonlocal last_push, pending
            p = cyanrip.parse_progress(line)
            if p is not None:
                if p.errors:
                    errors_in[p.track] = max(errors_in.get(p.track, 0), p.errors)
                for t in live.tracks:
                    if t.number == p.track:
                        t.percent = p.percent
                live.current, live.eta_seconds = p.track, p.eta_seconds
            else:
                rip_lines.append(line)
                self._jobs.log(rec.id, line, error=is_error_line(line))
                if line.lstrip().startswith(("Track ", "Accurip", "Preemphasis")):
                    self._apply(live, cyanrip.parse_report("\n".join(rip_lines)))
            # Throttle pushes, but always push the latest state eventually (trailing edge).
            now = loop.time()
            if p is None or now - last_push >= self.PUBLISH_EVERY:
                last_push = now
                loop.call_soon_threadsafe(self._publish)
            elif not pending:
                pending = True
                loop.call_soon_threadsafe(loop.call_later, self.PUBLISH_EVERY, push_pending)

        def push_pending() -> None:
            nonlocal pending, last_push
            pending, last_push = False, loop.time()
            self._publish()

        cwd = rec.scratch_dir.parent
        try:
            code = await self._run_tool(
                cyanrip.rip_command(exe, device, cfg.offset, rec.scratch_dir.name,
                                    cfg.retries), on_line, cwd)
        except FileNotFoundError:
            code = None
        self._jobs.step_exit(rec.id, code)

        # 3. Result: the .log is authoritative; stdout is the fallback.
        log_file = rec.scratch_dir / "rip.log"
        try:
            text = log_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = "\n".join(rip_lines)
        report = cyanrip.parse_report(text)
        self._apply(live, report)
        self._tracks.save(rec.id, live.tracks)
        if code is not None and cyanrip.rip_succeeded(report, code, len(tracks)):
            cue = rec.scratch_dir / "rip.cue"
            if cue.exists():
                cue.write_text(strip_data_tracks(cue.read_text(encoding="utf-8")),
                               encoding="utf-8")
            self._jobs.mark_ripped(rec.id)
            self._jobs.log(rec.id, "Rip finished")
            await self._eject(rec.id)
        else:
            if code is None:
                failure = NOT_INSTALLED
            elif any(_DRIVE_ERRORS.search(ln) for ln in rip_lines) and not report.tracks:
                failure = DRIVE
            else:
                bad = min(errors_in) if errors_in else \
                    next((t.number for t in live.tracks if not t.ripped), None)
                failure = _unreadable(bad, cfg.retries) \
                    if bad is not None and (errors_in or report.ripping_errors) else GENERIC
            await self._fail(rec, failure)
        self.current = None
        self._publish()

    def _apply(self, live: CdRip, report: Report) -> None:
        for t in live.tracks:
            r = report.tracks.get(t.number)
            if r is None:
                continue
            if r.ripped:
                t.ripped, t.percent = True, 100.0
            if r.ar is not None:
                t.ar = r.ar
            if r.preemphasis:
                t.preemphasis = True

    async def _fail(self, rec: JobRecord, failure: Failure) -> None:
        self._jobs.log(rec.id, failure.headline, error=True)
        await self._eject(rec.id)
        self._jobs.log(rec.id, "Removing partial files from scratch")
        await asyncio.to_thread(self._jobs.mark_failed, rec.id, failure)
        log.info("CD Rip %s failed: %s", rec.id, failure.kind)
        self.current = None
        self._publish()

