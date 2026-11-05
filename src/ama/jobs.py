"""Jobs: one row per Disc inserted and Ripped (or tried), shared by CD and video Rips.

A Job is one Disc's single pass through the pipeline (GLOSSARY.md); inserting the same
Disc again starts a new Job.

Persisted in SQLite (`jobs`, `job_log`, plus video `titles`) so a failure and
its log survive a restart, and so a Rip cut short by a restart can be cleaned
up. A record is `ripping` while the Rip runs, then `ripped` or `failed`. A
failed record keeps its log for the UI until the user dismisses it; its partial
scratch files are already gone. A `ripped` Job is then Identified: it goes to
`review` (a human must confirm the Identification) or is `filed` into the
Archive, which deletes its scratch.
"""

from __future__ import annotations

import builtins
import logging
import shutil
from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from ama.db import Database
from ama.drive import DiscType
from ama.runs import Runs

log = logging.getLogger(__name__)


class JobStatus(StrEnum):
    RIPPING = "ripping"
    RIPPED = "ripped"  # waiting for Identification / filing
    REVIEW = "review"  # Identification needs a human (see ReviewReason)
    FILED = "filed"    # in the Archive; scratch deleted
    FAILED = "failed"


class ReviewReason(StrEnum):
    """Why a Job's Identification couldn't be accepted automatically."""

    MULTIPLE_RELEASES = "multiple_releases"  # MusicBrainz knows several releases with this CD
    NO_RELEASE = "no_release"                # MusicBrainz doesn't know this CD
    NOT_ACCURATE = "not_accurate"            # a track didn't match AccurateRip
    NOT_IN_ACCURATERIP = "not_in_accuraterip"
    ACCURATERIP_UNAVAILABLE = "accuraterip_unavailable"  # couldn't be checked
    # video
    NO_MATCH = "no_match"                    # TMDB has no film named like the Disc
    RUNTIME_MISMATCH = "runtime_mismatch"    # films found, none within 5 min of the Main Feature
    MULTIPLE_MATCHES = "multiple_matches"    # several films fit name and runtime
    EPISODES = "episodes"                    # looks like TV: Titles -> Episodes needs a human
    DECOY_PLAYLISTS = "decoy_playlists"      # many near-identical Titles: which is the film?
    PICK_RUNTIME_MISMATCH = "pick_runtime_mismatch"  # the user's pick isn't within 5 min
    # CD
    PICK_NOT_FITTING = "pick_not_fitting"    # the release the user picked doesn't fit the Rip


class TitleStatus(StrEnum):
    WAITING = "waiting"
    RIPPING = "ripping"
    RIPPED = "ripped"
    FAILED = "failed"
    SKIPPED = "skipped"  # unticked by the user before its turn: never ripped (GLOSSARY)


class FailureKind(StrEnum):
    INTERRUPTED = "interrupted"  # the app stopped mid-Rip
    DISCARDED = "discarded"  # the user threw the Rip away in Review
    SCRATCH_CLEANED = "scratch_cleaned"  # Scratch cleanup removed a failed Encode's Rip
    # video
    LICENCE = "licence"  # MakeMKV refused to work: not the Disc's fault
    MAKEMKV = "makemkv"  # MakeMKV missing, or crashed
    DISC = "disc"  # couldn't read the Disc, or nothing on it to rip
    TITLE = "title"  # a Title couldn't be ripped
    LIBREDRIVE = "libredrive"  # a UHD the drive can't open without LibreDrive mode
    # CD
    NOT_INSTALLED = "not_installed"  # cyanrip missing
    NO_AUDIO = "no_audio"
    DRIVE = "drive"  # cyanrip couldn't open the drive
    RIP_ERROR = "rip_error"
    UNREADABLE_TRACK = "unreadable_track"


@dataclass(frozen=True)
class Failure:
    kind: FailureKind
    headline: str  # one sentence: what went wrong
    advice: str  # what the user can do about it


def format_duration(seconds: int) -> str:
    h, rest = divmod(seconds, 3600)
    return f"{h}:{rest // 60:02d}:{rest % 60:02d}"


def format_gb(size_bytes: int) -> str:
    return f"{size_bytes / 1000**3:.1f} GB"


@dataclass(frozen=True)
class TitleRecord:
    number: int
    makemkv_id: int
    duration_s: int
    size_bytes: int
    audio: int
    subtitles: int
    segments: str
    file: str
    status: TitleStatus = TitleStatus.WAITING
    source: str = ""  # the Disc's playlist, e.g. "00800.mpls" (TINFO 16; "" on older Rips)
    name: str = ""  # MakeMKV's name for the Title (TINFO 2); often just the Disc's name

    @property
    def duration(self) -> str:
        return format_duration(self.duration_s)

    @property
    def size(self) -> str:
        return format_gb(self.size_bytes)


@dataclass(frozen=True)
class LogLine:
    at: datetime
    error: bool
    text: str

    def __str__(self) -> str:
        return f"{self.at:%H:%M:%S}  {self.text}"


@dataclass(frozen=True)
class JobRecord:
    id: int
    disc_type: DiscType
    label: str
    status: JobStatus
    failure: Failure | None
    scratch_dir: Path
    started_at: datetime
    finished_at: datetime | None
    dismissed: bool
    skipped_short: int = 0
    skipped_duplicates: int = 0
    min_title_seconds: int = 30  # a video Rip's minimum Title length (ADR 0005)
    titles: tuple[TitleRecord, ...] = ()  # video Discs only
    review_reason: ReviewReason | None = None
    title: str = ""                 # what it was filed as, e.g. "Kid A — Radiohead"
    archive_dir: Path | None = None
    filed_at: datetime | None = None
    scratch_cleaned_at: datetime | None = None

    @property
    def name(self) -> str:
        return self.label or self.disc_type.long_name

    @property
    def to_rip(self) -> tuple[TitleRecord, ...]:
        """The Titles ripped or to be ripped: all but those Skipped."""
        return tuple(t for t in self.titles if t.status != TitleStatus.SKIPPED)

    @property
    def skipped_titles(self) -> tuple[TitleRecord, ...]:
        return tuple(t for t in self.titles if t.status == TitleStatus.SKIPPED)

    @property
    def all_skipped(self) -> bool:
        """Every Title was Skipped: the Job is Filed with nothing in it."""
        return bool(self.titles) and not self.to_rip

    @property
    def total_size(self) -> str:
        return format_gb(sum(t.size_bytes for t in self.to_rip))

    @property
    def skipped_note(self) -> str | None:
        """'Skipped by you: Title 2. It wasn't ripped, so it can't be kept.' for Review."""
        skipped = self.skipped_titles
        if not skipped:
            return None
        it = "It wasn't ripped, so it" if len(skipped) == 1 else "They weren't ripped, so they"
        return f"Skipped by you: {_numbers(skipped)}. {it} can't be kept."

    @property
    def skipped_summary(self) -> str | None:
        """'Not ripped: ...' sentence for the Title list, or None if nothing was skipped."""
        parts = []
        if self.all_skipped:
            n = len(self.titles)
            lead = f"All {n} Titles skipped by you." if n != 1 else "Its one Title skipped by you."
            rest = self._left_out()
            return f"{lead} Also not ripped: {' and '.join(rest)}." if rest else lead
        if self.skipped_titles:
            parts.append(f"{_numbers(self.skipped_titles)} skipped by you")
        parts += self._left_out()
        return f"Not ripped: {' and '.join(parts)}." if parts else None

    def _left_out(self) -> list[str]:
        """The Titles the Rip left out on its own: too short, or duplicates."""
        parts = []
        if self.skipped_short:
            n = self.skipped_short
            parts.append(f"{n} Title{'s' if n != 1 else ''} shorter than "
                         f"{self.min_title_seconds} seconds (menus, logos)")
        if self.skipped_duplicates:
            n = self.skipped_duplicates
            parts.append(f"{n} exact duplicate{'s' if n != 1 else ''} of other Titles")
        return parts


def _numbers(titles: tuple[TitleRecord, ...]) -> str:
    """'Title 2', 'Titles 2 and 4', 'Titles 2, 3 and 4'."""
    ns = [str(t.number) for t in titles]
    if len(ns) == 1:
        return f"Title {ns[0]}"
    return f"Titles {', '.join(ns[:-1])} and {ns[-1]}"


_COLS = ("id, disc_type, label, status, failure_kind, failure_headline, failure_advice, "
         "scratch_dir, started_at, finished_at, dismissed, skipped_short, skipped_duplicates, "
         "review_reason, title, archive_dir, filed_at, min_title_seconds, scratch_cleaned_at")


def _when(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _rip_name(rec: JobRecord) -> str:
    return f"{rec.disc_type.long_name} “{rec.label}” (Job {rec.id})"


class JobStore:
    def __init__(self, db: Database, scratch: Path,
                 now: Callable[[], datetime] = datetime.now, runs: Runs | None = None) -> None:
        self._db = db
        self._scratch = scratch
        self._now = now
        # Logs (runs.py): each Job's Run follows its records here; None keeps no Run.
        self.runs = runs
        # A Job may have finished (filed, failed, an Encode failed): Scratch cleanup looks again.
        self.finished: Callable[[], None] = lambda: None

    def _ts(self) -> str:
        return self._now().isoformat(timespec="seconds")

    def _set_status(self, job_id: int, status: JobStatus, sets: str = "",
                    params: tuple = (), only_if: str = "") -> bool:
        """Every status write goes through here, so it always stamps `changed_at`."""
        extra = f"{sets}, " if sets else ""
        cond = f" AND {only_if}" if only_if else ""
        cur = self._db.execute(
            f"UPDATE jobs SET status = ?, {extra}changed_at = ? WHERE id = ?{cond}",
            (status.value, *params, self._ts(), job_id))
        return cur.rowcount == 1

    def _record(self, row) -> JobRecord:
        (id_, dtype, label, status, fkind, fhead, fadv, scratch, started, finished, dismissed,
         short, dupes, reason, title, archive_dir, filed_at, min_title, cleaned_at) = row
        titles = self._db.execute(
            "SELECT number, makemkv_id, duration_s, size_bytes, audio, subtitles, segments, file, "
            "status, source, name FROM titles WHERE job_id = ? ORDER BY number",
            (id_,)).fetchall()
        return JobRecord(
            id=id_, disc_type=DiscType(dtype), label=label, status=JobStatus(status),
            failure=Failure(FailureKind(fkind), fhead or "", fadv or "") if fkind else None,
            scratch_dir=Path(scratch), started_at=datetime.fromisoformat(started),
            finished_at=datetime.fromisoformat(finished) if finished else None,
            dismissed=bool(dismissed), skipped_short=short, skipped_duplicates=dupes,
            min_title_seconds=min_title,
            titles=tuple(TitleRecord(*t[:8], status=TitleStatus(t[8]), source=t[9], name=t[10])
                         for t in titles),
            review_reason=ReviewReason(reason) if reason else None, title=title,
            archive_dir=Path(archive_dir) if archive_dir else None,
            filed_at=_when(filed_at), scratch_cleaned_at=_when(cleaned_at),
        )

    def create(self, disc_type: DiscType, label: str, scratch_subdir: str,
               min_title_seconds: int = 30) -> JobRecord:
        """Start a record in `ripping`; its scratch folder is `scratch/<subdir>/<id>`."""
        cur = self._db.execute(
            "INSERT INTO jobs (disc_type, label, status, scratch_dir, started_at, "
            "min_title_seconds, changed_at) VALUES (?, ?, 'ripping', '', ?, ?, ?)",
            (disc_type.value, label, self._ts(), min_title_seconds, self._ts()))
        job_id = cur.lastrowid
        assert job_id is not None
        scratch = self._scratch / scratch_subdir / str(job_id)
        self._db.execute("UPDATE jobs SET scratch_dir = ? WHERE id = ?", (str(scratch), job_id))
        job = self.get(job_id)
        assert job is not None
        log.info("Rip started: %s", _rip_name(job))
        if self.runs:
            self.runs.job_begin(job_id, "rip", "Rip",
                                tool="cyanrip" if disc_type == DiscType.CD else "makemkvcon")
        return job

    def get(self, job_id: int) -> JobRecord | None:
        row = self._db.execute(f"SELECT {_COLS} FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._record(row) if row else None

    def statuses(self) -> dict[int, JobStatus]:
        """Every Job's current status, by id (cheap: no Titles, no records)."""
        rows = self._db.execute("SELECT id, status FROM jobs").fetchall()
        return {id_: JobStatus(status) for id_, status in rows}

    def list(self, status: JobStatus, include_dismissed: bool = False,
             types: Collection[DiscType] | None = None) -> list[JobRecord]:
        """Records in `status`, newest first; only `types` if given."""
        rows = self._db.execute(
            f"SELECT {_COLS} FROM jobs WHERE status = ? AND (? OR dismissed = 0) "
            "ORDER BY id DESC", (status.value, include_dismissed)).fetchall()
        recs = [self._record(r) for r in rows]
        return [r for r in recs if types is None or r.disc_type in types]

    def set_titles(self, job_id: int, titles: Iterable[TitleRecord], skipped_short: int,
                   skipped_duplicates: int) -> None:
        self._db.execute("DELETE FROM titles WHERE job_id = ?", (job_id,))
        for t in titles:
            self._db.execute(
                "INSERT INTO titles (job_id, number, makemkv_id, duration_s, size_bytes, audio, "
                "subtitles, segments, file, status, source, name) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (job_id, t.number, t.makemkv_id, t.duration_s, t.size_bytes, t.audio,
                 t.subtitles, t.segments, t.file, str(t.status), t.source, t.name))
        self._db.execute("UPDATE jobs SET skipped_short = ?, skipped_duplicates = ? WHERE id = ?",
                         (skipped_short, skipped_duplicates, job_id))

    def move_title(self, job_id: int, number: int, before: TitleStatus,
                   after: TitleStatus) -> bool:
        """The Title goes from `before` to `after`; False (unchanged) if it wasn't `before`."""
        cur = self._db.execute(
            "UPDATE titles SET status = ? WHERE job_id = ? AND number = ? AND status = ?",
            (str(after), job_id, number, str(before)))
        return cur.rowcount == 1

    def set_title_status(self, job_id: int, number: int, status: TitleStatus) -> None:
        self._db.execute("UPDATE titles SET status = ? WHERE job_id = ? AND number = ?",
                         (str(status), job_id, number))

    def mark_ripped(self, job_id: int) -> None:
        self._set_status(job_id, JobStatus.RIPPED, "finished_at = ?", (self._ts(),))
        if rec := self.get(job_id):
            log.info("Rip finished: %s: ripped", _rip_name(rec))
        # The Rip Step carries on (the eject is still to come) until Identification begins.

    def mark_failed(self, job_id: int, failure: Failure) -> None:
        """Fail the record and delete its partial scratch files (idempotent)."""
        rec = self.get(job_id)
        if rec is None:
            return
        if rec.status == JobStatus.RIPPING:
            log.info("Rip finished: %s: failed (%s)", _rip_name(rec), failure.headline)
        shutil.rmtree(rec.scratch_dir, ignore_errors=True)
        if self.runs:
            self.runs.flush()  # its Step's last lines (why it failed) before the Job reads failed
        self._set_status(
            job_id, JobStatus.FAILED, "failure_kind = ?, failure_headline = ?, "
            "failure_advice = ?, finished_at = COALESCE(finished_at, ?)",
            (failure.kind.value, failure.headline, failure.advice, self._ts()))
        self._db.execute("UPDATE titles SET status = 'failed' WHERE job_id = ? "
                         "AND status = 'ripping'", (job_id,))
        if self.runs:
            self.runs.job_end(job_id, failed=True, result=failure.headline, finish=True)
        self.finished()

    def mark_review(self, job_id: int, reason: ReviewReason) -> None:
        self._set_status(job_id, JobStatus.REVIEW, "review_reason = ?", (reason.value,))
        if self.runs:
            self.runs.job_end(job_id, result="Needs Review")

    def requeue(self, job_id: int) -> bool:
        """Review is decided: back to `ripped` for its worker to file. False if not in Review."""
        return self._set_status(job_id, JobStatus.RIPPED, "review_reason = NULL",
                                only_if="status = 'review'")

    def mark_filed(self, job_id: int, title: str, archive_dir: Path) -> None:
        """Record the Disc as filed, then delete its scratch (`clean_filed_scratch` finishes a
        cut-off delete)."""
        self._set_status(
            job_id, JobStatus.FILED, "review_reason = NULL, title = ?, archive_dir = ?, "
            "filed_at = COALESCE(filed_at, ?)", (title, str(archive_dir), self._ts()))
        rec = self.get(job_id)
        if rec is not None:
            shutil.rmtree(rec.scratch_dir, ignore_errors=True)
        self.finished()

    def encode_failed(self, job_id: int) -> None:
        """A Title Encode failed: the Job's Encode changed status, and it may now be
        finished, its Scratch kept for a retry until Scratch cleanup removes it."""
        self._db.execute("UPDATE jobs SET changed_at = ? WHERE id = ?", (self._ts(), job_id))
        self.finished()

    def kept_scratch(self, changed_before: datetime) -> builtins.list[JobRecord]:
        """Finished Jobs whose Scratch is kept (a failed Encode, nothing else of the Job
        still to Encode or file) that last changed status before `changed_before`, oldest
        first."""
        rows = self._db.execute(
            f"SELECT {_COLS} FROM jobs j WHERE status = 'ripped' "
            "AND scratch_cleaned_at IS NULL AND changed_at < ? AND ("
            "EXISTS (SELECT 1 FROM movies m WHERE m.job_id = j.id "
            "AND m.encode_status = 'failed') "
            "OR (EXISTS (SELECT 1 FROM tv_titles t WHERE t.job_id = j.id "
            "AND t.encode_status = 'failed') "
            "AND NOT EXISTS (SELECT 1 FROM tv_titles t WHERE t.job_id = j.id "
            "AND t.encode_status NOT IN ('failed', 'filed')))) "
            "ORDER BY changed_at, id",
            (changed_before.isoformat(timespec="seconds"),)).fetchall()
        return [self._record(r) for r in rows]

    def mark_scratch_cleaned(self, job_id: int, failure: Failure) -> bool:
        """Scratch cleanup fails the Job for good; False if another pass took it first."""
        if not self._set_status(
                job_id, JobStatus.FAILED, "failure_kind = ?, failure_headline = ?, "
                "failure_advice = ?, scratch_cleaned_at = ?",
                (failure.kind.value, failure.headline, failure.advice, self._ts()),
                only_if="status = 'ripped' AND scratch_cleaned_at IS NULL"):
            return False
        if self.runs:
            self.runs.job_end(job_id, failed=True, finish=True)
        return True

    def scratch_left(self) -> builtins.list[JobRecord]:
        """Jobs Scratch cleanup took whose files are still there (it was cut off)."""
        rows = self._db.execute(f"SELECT {_COLS} FROM jobs WHERE scratch_cleaned_at IS NOT NULL "
                                "ORDER BY changed_at, id").fetchall()
        return [rec for r in rows if (rec := self._record(r)).scratch_dir.exists()]

    def mark_filed_empty(self, job_id: int) -> None:
        """Every Title was Skipped: Filed with nothing in it (its Scratch is the caller's)."""
        self._set_status(
            job_id, JobStatus.FILED, "review_reason = NULL, "
            "finished_at = COALESCE(finished_at, ?), filed_at = COALESCE(filed_at, ?)",
            (self._ts(), self._ts()))
        rec = self.get(job_id)
        if rec is None:
            return
        log.info("Rip finished: %s: every Title skipped", _rip_name(rec))
        if self.runs:
            self.runs.job_end(job_id, result=rec.skipped_summary, finish=True)

    def clean_filed_scratch(self) -> None:
        for rec in self.list(JobStatus.FILED, include_dismissed=True):
            if rec.scratch_dir.exists():
                shutil.rmtree(rec.scratch_dir, ignore_errors=True)

    def dismiss(self, job_id: int) -> None:
        self._db.execute("UPDATE jobs SET dismissed = 1 WHERE id = ?", (job_id,))

    def log(self, job_id: int, text: str, error: bool = False, in_step: bool = True) -> None:
        """A line for the Job's log, and (`in_step`) for its running Step's output in Logs."""
        self._db.execute("INSERT INTO job_log (job_id, at, error, text) VALUES (?, ?, ?, ?)",
                         (job_id, self._ts(), int(error), text))
        if self.runs and in_step:
            self.runs.job_note(job_id, text, error)

    # --- the Job's Steps in Logs (runs.py), beyond what the methods above record ---

    def begin_step(self, job_id: int, key: str, name: str, tool: str = "",
                   subject: str = "", fresh: bool = True) -> None:
        """`fresh=False`: a Step taken up again (TV files Title by Title) keeps its output."""
        if self.runs:
            self.runs.job_begin(job_id, key, name, tool, subject, fresh)

    def finish_run(self, job_id: int) -> None:
        """Filing is over (the Plex scan asked for): the Job's Run is done."""
        if self.runs:
            self.runs.job_end(job_id, finish=True)

    def step_output(self, job_id: int, text: str, error: bool = False) -> None:
        """A tool's own output line for the running Step: Logs only, not the Job's log."""
        if self.runs:
            self.runs.job_note(job_id, text, error)

    def step_exit(self, job_id: int, exit_code: int | None) -> None:
        """The running Step's tool exited (the Step itself may have more to do)."""
        if self.runs and exit_code is not None:
            self.runs.job_exit(job_id, exit_code)

    def end_step(self, job_id: int, failed: bool = False, exit_code: int | None = None,
                 result: str | None = None) -> None:
        if self.runs:
            self.runs.job_end(job_id, failed, exit_code, result)

    def log_lines(self, job_id: int) -> builtins.list[LogLine]:  # `list` here is the method above
        rows = self._db.execute(
            "SELECT at, error, text FROM job_log WHERE job_id = ? ORDER BY id",
            (job_id,)).fetchall()
        return [LogLine(datetime.fromisoformat(a), bool(e), t) for a, e, t in rows]

    def encode_started(self, job_id: int, title_number: int) -> None:
        """A Title's Encode began (again, after a failure or restart: the clock restarts)."""
        self._db.execute(
            "INSERT INTO encode_times (job_id, title_number, started_at) VALUES (?, ?, ?) "
            "ON CONFLICT (job_id, title_number) DO UPDATE SET started_at = excluded.started_at, "
            "finished_at = NULL", (job_id, title_number, self._ts()))
        self.begin_step(job_id, f"encode:{title_number}", "Encode", tool="ffmpeg")

    def encode_finished(self, job_id: int, title_number: int) -> None:
        self._db.execute("UPDATE encode_times SET finished_at = ? "
                         "WHERE job_id = ? AND title_number = ?",
                         (self._ts(), job_id, title_number))
        self.end_step(job_id, exit_code=0)

    def encode_times(self, job_id: int) -> dict[int, tuple[datetime, datetime | None]]:
        """Title number -> (Encode started, finished or None) for each Title Encoded so far."""
        rows = self._db.execute("SELECT title_number, started_at, finished_at FROM encode_times "
                                "WHERE job_id = ?", (job_id,)).fetchall()
        return {n: (datetime.fromisoformat(s), datetime.fromisoformat(f) if f else None)
                for n, s, f in rows}
