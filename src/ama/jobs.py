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

log = logging.getLogger(__name__)


class JobStatus(StrEnum):
    RIPPING = "ripping"
    RIPPED = "ripped"  # waiting for Identification / filing
    REVIEW = "review"  # Identification needs a human (see ReviewReason)
    FILED = "filed"    # in the Archive; scratch deleted
    FAILED = "failed"


class ReviewReason(StrEnum):
    """Why a Disc's Identification couldn't be accepted automatically."""

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


class TitleStatus(StrEnum):
    WAITING = "waiting"
    RIPPING = "ripping"
    RIPPED = "ripped"
    FAILED = "failed"


class FailureKind(StrEnum):
    INTERRUPTED = "interrupted"  # the app stopped mid-Rip
    DISCARDED = "discarded"  # the user threw the Rip away in Review
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
    titles: tuple[TitleRecord, ...] = ()  # video Discs only
    review_reason: ReviewReason | None = None
    title: str = ""                 # what it was filed as, e.g. "Kid A — Radiohead"
    archive_dir: Path | None = None
    filed_at: datetime | None = None

    @property
    def name(self) -> str:
        return self.label or self.disc_type.long_name

    @property
    def total_size(self) -> str:
        return format_gb(sum(t.size_bytes for t in self.titles))

    @property
    def skipped_summary(self) -> str | None:
        """'Not ripped: ...' sentence for the Title list, or None if nothing was skipped."""
        parts = []
        if self.skipped_short:
            n = self.skipped_short
            parts.append(f"{n} Title{'s' if n != 1 else ''} shorter than 30 seconds (menus, logos)")
        if self.skipped_duplicates:
            n = self.skipped_duplicates
            parts.append(f"{n} exact duplicate{'s' if n != 1 else ''} of other Titles")
        return f"Not ripped: {' and '.join(parts)}." if parts else None


_COLS = ("id, disc_type, label, status, failure_kind, failure_headline, failure_advice, "
         "scratch_dir, started_at, finished_at, dismissed, skipped_short, skipped_duplicates, "
         "review_reason, title, archive_dir, filed_at")


def _rip_name(rec: JobRecord) -> str:
    return f"{rec.disc_type.long_name} “{rec.label}” (Job {rec.id})"


class JobStore:
    def __init__(self, db: Database, scratch: Path,
                 now: Callable[[], datetime] = datetime.now) -> None:
        self._db = db
        self._scratch = scratch
        self._now = now

    def _ts(self) -> str:
        return self._now().isoformat(timespec="seconds")

    def _record(self, row) -> JobRecord:
        (id_, dtype, label, status, fkind, fhead, fadv, scratch, started, finished, dismissed,
         short, dupes, reason, title, archive_dir, filed_at) = row
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
            titles=tuple(TitleRecord(*t[:8], status=TitleStatus(t[8]), source=t[9], name=t[10])
                         for t in titles),
            review_reason=ReviewReason(reason) if reason else None, title=title,
            archive_dir=Path(archive_dir) if archive_dir else None,
            filed_at=datetime.fromisoformat(filed_at) if filed_at else None,
        )

    def create(self, disc_type: DiscType, label: str, scratch_subdir: str) -> JobRecord:
        """Start a record in `ripping`; its scratch folder is `scratch/<subdir>/<id>`."""
        cur = self._db.execute(
            "INSERT INTO jobs (disc_type, label, status, scratch_dir, started_at) "
            "VALUES (?, ?, 'ripping', '', ?)", (disc_type.value, label, self._ts()))
        job_id = cur.lastrowid
        assert job_id is not None
        scratch = self._scratch / scratch_subdir / str(job_id)
        self._db.execute("UPDATE jobs SET scratch_dir = ? WHERE id = ?", (str(scratch), job_id))
        job = self.get(job_id)
        assert job is not None
        log.info("Rip started: %s", _rip_name(job))
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

    def set_title_status(self, job_id: int, number: int, status: TitleStatus) -> None:
        self._db.execute("UPDATE titles SET status = ? WHERE job_id = ? AND number = ?",
                         (str(status), job_id, number))

    def mark_ripped(self, job_id: int) -> None:
        self._db.execute("UPDATE jobs SET status = 'ripped', finished_at = ? WHERE id = ?",
                         (self._ts(), job_id))
        if rec := self.get(job_id):
            log.info("Rip finished: %s: ripped", _rip_name(rec))

    def mark_failed(self, job_id: int, failure: Failure) -> None:
        """Fail the record and delete its partial scratch files (idempotent)."""
        rec = self.get(job_id)
        if rec is None:
            return
        if rec.status == JobStatus.RIPPING:
            log.info("Rip finished: %s: failed (%s)", _rip_name(rec), failure.headline)
        shutil.rmtree(rec.scratch_dir, ignore_errors=True)
        self._db.execute(
            "UPDATE jobs SET status = 'failed', failure_kind = ?, failure_headline = ?, "
            "failure_advice = ?, finished_at = COALESCE(finished_at, ?) WHERE id = ?",
            (failure.kind.value, failure.headline, failure.advice, self._ts(), job_id))
        self._db.execute("UPDATE titles SET status = 'failed' WHERE job_id = ? "
                         "AND status = 'ripping'", (job_id,))

    def mark_review(self, job_id: int, reason: ReviewReason) -> None:
        self._db.execute("UPDATE jobs SET status = 'review', review_reason = ? WHERE id = ?",
                         (reason.value, job_id))

    def requeue(self, job_id: int) -> bool:
        """Review is decided: back to `ripped` for its worker to file. False if not in Review."""
        cur = self._db.execute("UPDATE jobs SET status = 'ripped', review_reason = NULL "
                               "WHERE id = ? AND status = 'review'", (job_id,))
        return cur.rowcount == 1

    def mark_filed(self, job_id: int, title: str, archive_dir: Path) -> None:
        """Record the Disc as filed, then delete its scratch (`clean_filed_scratch` finishes a
        cut-off delete)."""
        self._db.execute(
            "UPDATE jobs SET status = 'filed', review_reason = NULL, title = ?, archive_dir = ?, "
            "filed_at = COALESCE(filed_at, ?) WHERE id = ?",
            (title, str(archive_dir), self._ts(), job_id))
        rec = self.get(job_id)
        if rec is not None:
            shutil.rmtree(rec.scratch_dir, ignore_errors=True)

    def clean_filed_scratch(self) -> None:
        for rec in self.list(JobStatus.FILED, include_dismissed=True):
            if rec.scratch_dir.exists():
                shutil.rmtree(rec.scratch_dir, ignore_errors=True)

    def dismiss(self, job_id: int) -> None:
        self._db.execute("UPDATE jobs SET dismissed = 1 WHERE id = ?", (job_id,))

    def log(self, job_id: int, text: str, error: bool = False) -> None:
        self._db.execute("INSERT INTO job_log (job_id, at, error, text) VALUES (?, ?, ?, ?)",
                         (job_id, self._ts(), int(error), text))

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

    def encode_finished(self, job_id: int, title_number: int) -> None:
        self._db.execute("UPDATE encode_times SET finished_at = ? "
                         "WHERE job_id = ? AND title_number = ?",
                         (self._ts(), job_id, title_number))

    def encode_times(self, job_id: int) -> dict[int, tuple[datetime, datetime | None]]:
        """Title number -> (Encode started, finished or None) for each Title Encoded so far."""
        rows = self._db.execute("SELECT title_number, started_at, finished_at FROM encode_times "
                                "WHERE job_id = ?", (job_id,)).fetchall()
        return {n: (datetime.fromisoformat(s), datetime.fromisoformat(f) if f else None)
                for n, s, f in rows}
