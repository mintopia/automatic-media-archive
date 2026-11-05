"""Video Rip to scratch: a DVD/BD/UHD in the drive is ripped with makemkvcon, then ejected.

Every Title >= 30 s is ripped (exact duplicates dropped) into
`scratch/video/<Job id>/`, one `makemkvcon mkv` run per Title, regardless of
Identification (ADR-0005). On any failure the Disc is ejected, marked failed
with its log, and its partial files are deleted. Nothing is retried on its own:
a Disc is ripped once per insertion.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ama import makemkv
from ama.jobs import (
    JobRecord,
    JobStatus,
    JobStore,
    Failure,
    FailureKind,
    TitleRecord,
    TitleStatus,
)
from ama.drive import DiscPresent, DiscType, DriveMonitor, DriveState
from ama.events import EventBus, Topic
from ama.makemkv import Msg, Progress, RobotLine
from ama.pause import Pause
from ama.proc import Streamer
from ama.repeat import RepeatGuard, video_fingerprint
from ama.scratch import ScratchGate
from ama.media import Screen
from ama.tmdb import DiscHints, bd_meta_title, save_hints
from ama.tools import ToolUnavailable, makemkv_headline

log = logging.getLogger(__name__)

MIN_TITLE_SECONDS = 30  # ADR-0005
VIDEO_DISC_TYPES = frozenset({DiscType.DVD, DiscType.BD, DiscType.UHD})
PUBLISH_EVERY_SECONDS = 0.5

_DISC_ADVICE = ("This usually means a scratch or smudge. Clean the Disc and insert it again. "
                "If it fails a second time, the Disc may be damaged.")
LICENCE_FAILURE = Failure(
    FailureKind.LICENCE, "MakeMKV says its licence key isn't valid.",
    "DVDs and Blu-rays can't be ripped until the key is fixed. CDs still work. Open MakeMKV "
    "on the archive PC, go to Help → Register, and enter the key again.")
LIBREDRIVE_FAILURE = Failure(
    FailureKind.LIBREDRIVE, "The drive can't decrypt this UHD Blu-ray.",
    "UHD Blu-rays need MakeMKV's LibreDrive mode, and the drive isn't in it. This isn't a "
    "problem with the Disc. Open MakeMKV on the archive PC once (it switches the drive into "
    "LibreDrive mode), close it, then insert the Disc again. If MakeMKV's drive information "
    "says LibreDrive isn't possible, the drive needs MakeMKV's firmware update.")
INTERRUPTED_FAILURE = Failure(
    FailureKind.INTERRUPTED, "The app stopped during the Rip.",
    "The partial Rip was thrown away. Insert the Disc again to rip it from the start.")


@dataclass(frozen=True)
class RipProgress:
    """Live state of the Rip in progress (memory only; titles live on the JobRecord)."""

    title_number: int | None = None  # the Title being ripped; None while reading the Disc
    title_fraction: float = 0.0
    overall: float = 0.0
    eta_s: int | None = None

    @property
    def title_pct(self) -> int:
        return int(self.title_fraction * 100)

    @property
    def pct(self) -> int:
        return int(self.overall * 100)

    @property
    def eta(self) -> str | None:
        if self.eta_s is None:
            return None
        minutes = max(1, round(self.eta_s / 60))
        return f"{minutes} min left" if minutes < 60 else f"{minutes // 60} h {minutes % 60} m left"


def title_records(keep: list[makemkv.TitleInfo]) -> list[TitleRecord]:
    """The Titles to rip, numbered 1.. as people see them."""
    return [TitleRecord(number=n, makemkv_id=t.id, duration_s=t.duration_s,
                        size_bytes=t.size_bytes, audio=t.audio, subtitles=t.subtitles,
                        segments=t.segments_map, file=t.output_file or f"title_t{t.id:02d}.mkv",
                        source=t.source, name=t.name)
            for n, t in enumerate(keep, start=1)]


class _Aborted(Exception):
    pass


class _Fail(Exception):
    def __init__(self, failure: Failure) -> None:
        self.failure = failure


class VideoRipper:

    def __init__(self, drive: DriveMonitor, store: JobStore, bus: EventBus,
                 makemkvcon: Callable[[], Path], streamer: Streamer, repeat: RepeatGuard,
                 scratch: ScratchGate, pause: Pause,
                 clock: Callable[[], float] = time.monotonic,
                 disc_root: Callable[[], Path | None] = lambda: None,
                 guess: Callable[[str], Screen | None] | None = None,
                 hold: Callable[[], bool] = lambda: False) -> None:
        self._pause = pause
        self._hold = hold  # start no new Rip (a restart is waiting)
        self._guesser = guess  # a likely film from the volume label (Tmdb.guess)
        self.likely: Screen | None = None  # a guessed film while ripping; only for show
        self._drive = drive
        self._scratch = scratch
        self._disc_root = disc_root  # the Disc's filesystem root, for its BD metadata title
        self._store = store
        self._bus = bus
        self._repeat = repeat
        self._exe = makemkvcon
        self._run_lines = streamer
        self._clock = clock
        self.job: JobRecord | None = None  # the Disc being ripped, else the last one this run
        self.progress: RipProgress | None = None  # set only while ripping
        self._handled: int | None = None  # the `DriveMonitor.insertion` already dealt with
        self._abort = False
        self._last_publish = 0.0
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def active(self) -> JobRecord | None:
        return self.job if self.progress is not None else None

    # -- lifecycle ---------------------------------------------------------

    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        await self.recover()
        with self._bus.subscribe() as q:
            while True:
                await self._consider(self._drive.state)
                await q.get()
                while not q.empty():
                    q.get_nowait()

    async def recover(self) -> None:
        """A Rip cut short by a restart: fail it, delete its files, eject its Disc."""
        stale = self._store.list(JobStatus.RIPPING, include_dismissed=True,
                                 types=VIDEO_DISC_TYPES)
        for d in stale:
            self._store.mark_failed(d.id, INTERRUPTED_FAILURE)
            self._store.log(d.id, "The app stopped during the Rip; partial files removed",
                            error=True)
        if not stale:
            return
        await self._drive.poll_once()
        if self._is_video(self._drive.state):
            try:
                await self._drive.eject()
            except OSError:
                log.exception("eject failed")
        self._publish()

    @staticmethod
    def _is_video(state: DriveState) -> bool:
        return isinstance(state, DiscPresent) and state.disc_type in VIDEO_DISC_TYPES

    async def _consider(self, state: DriveState) -> None:
        if not self._is_video(state):
            return
        if self._handled == self._drive.insertion:  # once per insertion: never re-rip on our own
            return
        if self._pause.paused or self._hold():  # left unhandled: picked up when either ends
            return
        self._handled = self._drive.insertion
        assert isinstance(state, DiscPresent)
        # A known Disc waits for the user first; one they want again still needs room.
        fingerprint = await asyncio.to_thread(video_fingerprint, self._disc_root(),
                                              state.disc_type)
        if not await self._repeat.admit(state.disc_type, fingerprint):
            return
        if await self._scratch.refuses(state.disc_type, state.label):  # ejected unripped
            return
        await self.rip(state, fingerprint)

    # -- the Rip -----------------------------------------------------------

    async def rip(self, inserted: DiscPresent, fingerprint: str | None = None) -> None:
        self._loop = asyncio.get_running_loop()
        self._abort = False
        job = self._store.create(inserted.disc_type, inserted.label, "video")
        self._repeat.remember(job.id, fingerprint)
        shutil.rmtree(job.scratch_dir, ignore_errors=True)
        job.scratch_dir.mkdir(parents=True, exist_ok=True)
        self.job, self.progress, self.likely = job, RipProgress(), None
        self._store.log(job.id, f"Ripping {inserted.disc_type.long_name} “{job.name}”")
        self._publish()
        guessing = asyncio.create_task(self._guess(job.label))             if self._guesser and job.label else None
        try:
            failure = await self._rip_titles(job)
        except asyncio.CancelledError:
            self._abort = True  # stops makemkvcon; recover() cleans up on next start
            raise
        except Exception:
            log.exception("video rip crashed")
            failure = Failure(FailureKind.MAKEMKV, "Something went wrong during the Rip.",
                              "Insert the Disc again to retry. If it keeps happening, check "
                              "the app's log file.")
        if failure:
            self._store.log(job.id, failure.headline, error=True)
            self._store.log(job.id, "Removing partial files from scratch")
            self._store.mark_failed(job.id, failure)
        else:
            self._store.log(job.id, "Rip complete")
            self._store.mark_ripped(job.id)
        try:
            await self._drive.eject()
            self._store.log(job.id, "Disc ejected")
        except OSError as e:
            log.warning("eject failed: %s", e)
            self._store.log(job.id, f"Couldn't eject the Disc: {e}", error=True)
        if guessing:
            guessing.cancel()
        self.job, self.progress, self.likely = self._store.get(job.id), None, None
        self._publish()

    async def _guess(self, label: str) -> None:
        assert self._guesser is not None
        try:
            self.likely = await asyncio.to_thread(self._guesser, label)
        except Exception:
            log.exception("film guess failed")
            return
        if self.likely is not None and self.progress is not None:
            self._publish()

    async def _rip_titles(self, job: JobRecord) -> Failure | None:
        try:
            exe = self._exe()
        except ToolUnavailable as e:  # the MakeMKV preflight hasn't passed (ADR 0006)
            return Failure(FailureKind.LICENCE, makemkv_headline(e.status),
                           "DVDs and Blu-rays can't be ripped until MakeMKV is fixed. CDs still "
                           "work. The MakeMKV page says what to do.")
        try:
            _, out = await self._makemkv(job, makemkv.drives_args(exe), quiet=True)
            source = makemkv.pick_source(makemkv.parse_scan_records(out).drives)
            if source is None:
                return Failure(FailureKind.MAKEMKV, "MakeMKV can't see the drive.",
                               "Check the drive is connected, close the MakeMKV window if it's "
                               "open, then insert the Disc again.")
            scan = await self._scan(job, exe, source)
            if makemkv.libredrive_refused(scan.messages):
                # LibreDrive mode can drop when the drive resets; a fresh scan may bring it back
                self._store.log(job.id, "Reading the Disc once more, in case the drive "
                                         "switches to LibreDrive mode")
                scan = await self._scan(job, exe, source)
                if makemkv.libredrive_refused(scan.messages):
                    return LIBREDRIVE_FAILURE
            await self._save_hints(job, scan)
            if not scan.titles:
                return Failure(FailureKind.DISC, "MakeMKV couldn't read this Disc.", _DISC_ADVICE)
            sel = makemkv.select_titles(scan.titles, MIN_TITLE_SECONDS)
            if not sel.keep:
                return Failure(FailureKind.DISC, "There are no Titles of 30 seconds or more.",
                               "Nothing on this Disc looks worth archiving.")
            titles = title_records(sel.keep)
            self._store.set_titles(job.id, titles,
                                   skipped_short=scan.skipped_short + len(sel.short),
                                   skipped_duplicates=scan.skipped_duplicates + len(sel.duplicates))
            number = {t.makemkv_id: t.number for t in titles}
            for _dup, of in sel.duplicates:
                self._store.log(job.id, f"Skipping a Title with the same segments as "
                                         f"Title {number[of.id]}")
            self._store.log(job.id, f"{len(titles)} Titles to rip")
            self._refresh(job.id)
            total = sum(t.size_bytes for t in titles) or 1
            done = 0
            started: float | None = None
            for t in titles:
                self._store.set_title_status(job.id, t.number, TitleStatus.RIPPING)
                self._refresh(job.id)
                self.progress = RipProgress(t.number, 0.0, done / total, self._eta(started, done / total))
                self._publish()
                saving = False

                def on_progress(rec: RobotLine, t: TitleRecord = t, done: int = done) -> None:
                    nonlocal saving, started
                    if isinstance(rec, Msg) and rec.code == makemkv.MSG_SAVING:
                        saving = True
                        started = started if started is not None else self._clock()
                    elif isinstance(rec, Progress) and saving:
                        overall = (done + rec.fraction * t.size_bytes) / total
                        self.progress = RipProgress(t.number, rec.fraction, overall,
                                                    self._eta(started, overall))
                        self._publish_soon()

                code, out = await self._makemkv(
                    job, makemkv.mkv_args(exe, source, t.makemkv_id, job.scratch_dir,
                                           MIN_TITLE_SECONDS), on_progress)
                summary = makemkv.rip_summary(out)
                ok = (code == 0 and (job.scratch_dir / t.file).exists()
                      and (summary is None or (summary[0] >= 1 and summary[1] == 0)))
                if not ok:
                    self._store.set_title_status(job.id, t.number, TitleStatus.FAILED)
                    return Failure(FailureKind.TITLE, f"Title {t.number} couldn't be ripped.",
                                   _DISC_ADVICE)
                self._store.set_title_status(job.id, t.number, TitleStatus.RIPPED)
                self._store.log(job.id, f"Title {t.number} ripped ({t.size})")
                done += t.size_bytes
            return None
        except _Fail as f:
            return f.failure

    async def _scan(self, job: JobRecord, exe: Path, source: str) -> makemkv.Scan:
        _, out = await self._makemkv(job, makemkv.info_args(exe, source, MIN_TITLE_SECONDS))
        return makemkv.parse_scan_records(out)

    async def _save_hints(self, job: JobRecord, scan: makemkv.Scan) -> None:
        """Keep what the Disc says it is, for Identification after it's ejected."""
        root = self._disc_root()
        bd_title = await asyncio.to_thread(bd_meta_title, root) if root else ""
        save_hints(job.scratch_dir, DiscHints(volume_label=job.label, disc_name=scan.disc_name,
                                               bd_title=bd_title, volume_name=scan.volume_name))

    def _eta(self, started: float | None, overall: float) -> int | None:
        if started is None or overall < 0.01:
            return None
        elapsed = self._clock() - started
        if elapsed < 10:
            return None
        return int(elapsed * (1 - overall) / overall)

    async def _makemkv(self, job: JobRecord, args: list[str],
                       on_record: Callable[[RobotLine], None] | None = None,
                       quiet: bool = False) -> tuple[int, list[RobotLine]]:
        """Run makemkvcon, logging its messages (only licence ones if `quiet`); raises _Fail on a
        licence error or if it won't start."""
        records: list[RobotLine] = []
        licence = False

        def on_line(line: str) -> None:
            nonlocal licence
            if self._abort:
                raise _Aborted
            rec = makemkv.parse_line(line)
            if rec is None:
                return
            records.append(rec)
            if isinstance(rec, Msg):
                bad_licence = makemkv.licence_problem(rec, job.disc_type)
                licence = licence or bad_licence
                if bad_licence or not quiet:
                    self._store.log(job.id, rec.text, error=rec.is_error or bad_licence)
            if on_record:
                on_record(rec)

        try:
            code = await asyncio.to_thread(self._run_lines, args, on_line)
        except OSError as e:
            raise _Fail(Failure(
                FailureKind.MAKEMKV, "MakeMKV couldn't be started.",
                f"Check MakeMKV is installed on the archive PC ({args[0]}), then insert the "
                f"Disc again. Windows said: {e.strerror or e}")) from None
        if licence:
            raise _Fail(LICENCE_FAILURE)
        if code != 0 and args[-1] != "disc:9999":  # a drive listing's exit code means nothing
            self._store.log(job.id, f"makemkvcon exited with code {code}", error=True)
        if args[-1] != "disc:9999":
            self._store.step_exit(job.id, code)
        return code, records

    # -- publishing (the UI re-renders from .job / .progress) -------------

    def _refresh(self, job_id: int) -> None:
        self.job = self._store.get(job_id)

    def _publish(self) -> None:
        self._last_publish = self._clock()
        self._bus.publish(Topic.RIP)
        self._bus.publish(Topic.DRIVE)

    def _publish_soon(self) -> None:
        """From the makemkvcon thread: publish on the loop, at most every PUBLISH_EVERY_SECONDS."""
        if self._clock() - self._last_publish < PUBLISH_EVERY_SECONDS or self._loop is None:
            return
        self._last_publish = self._clock()
        self._loop.call_soon_threadsafe(self._publish)
