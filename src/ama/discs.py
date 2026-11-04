"""Disc records: one row per Disc AMA Ripped (or tried to), shared by CD and video Rips.

Persisted in SQLite (`discs`, `disc_log`, plus video `titles`) so a failure and
its log survive a restart, and so a Rip cut short by a restart can be cleaned
up. A record is `ripping` while the Rip runs, then `ripped` or `failed`. A
failed record keeps its log for the UI until the user dismisses it; its partial
scratch files are already gone.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from ama.db import Database
from ama.drive import DiscType


class DiscStatus(StrEnum):
    RIPPING = "ripping"
    RIPPED = "ripped"
    FAILED = "failed"


class TitleStatus(StrEnum):
    WAITING = "waiting"
    RIPPING = "ripping"
    RIPPED = "ripped"
    FAILED = "failed"


class FailureKind(StrEnum):
    INTERRUPTED = "interrupted"  # the app stopped mid-Rip
    # video
    LICENCE = "licence"  # MakeMKV refused to work: not the Disc's fault
    MAKEMKV = "makemkv"  # MakeMKV missing, or crashed
    DISC = "disc"  # couldn't read the Disc, or nothing on it to rip
    TITLE = "title"  # a Title couldn't be ripped
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
class DiscRecord:
    id: int
    disc_type: DiscType
    label: str
    status: DiscStatus
    failure: Failure | None
    scratch_dir: Path
    started_at: datetime
    finished_at: datetime | None
    dismissed: bool
    skipped_short: int = 0
    skipped_duplicates: int = 0
    titles: tuple[TitleRecord, ...] = ()  # video Discs only

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
         "scratch_dir, started_at, finished_at, dismissed, skipped_short, skipped_duplicates")


class DiscStore:
    def __init__(self, db: Database, scratch: Path,
                 now: Callable[[], datetime] = datetime.now) -> None:
        self._db = db
        self._scratch = scratch
        self._now = now

    def _ts(self) -> str:
        return self._now().isoformat(timespec="seconds")

    def _record(self, row) -> DiscRecord:
        (id_, dtype, label, status, fkind, fhead, fadv, scratch, started, finished, dismissed,
         short, dupes) = row
        titles = self._db.execute(
            "SELECT number, makemkv_id, duration_s, size_bytes, audio, subtitles, segments, file, "
            "status FROM titles WHERE disc_id = ? ORDER BY number", (id_,)).fetchall()
        return DiscRecord(
            id=id_, disc_type=DiscType(dtype), label=label, status=DiscStatus(status),
            failure=Failure(FailureKind(fkind), fhead or "", fadv or "") if fkind else None,
            scratch_dir=Path(scratch), started_at=datetime.fromisoformat(started),
            finished_at=datetime.fromisoformat(finished) if finished else None,
            dismissed=bool(dismissed), skipped_short=short, skipped_duplicates=dupes,
            titles=tuple(TitleRecord(*t[:8], status=TitleStatus(t[8])) for t in titles),
        )

    def create(self, disc_type: DiscType, label: str, scratch_subdir: str) -> DiscRecord:
        """Start a record in `ripping`; its scratch folder is `scratch/<subdir>/<id>`."""
        cur = self._db.execute(
            "INSERT INTO discs (disc_type, label, status, scratch_dir, started_at) "
            "VALUES (?, ?, 'ripping', '', ?)", (disc_type.value, label, self._ts()))
        disc_id = cur.lastrowid
        assert disc_id is not None
        scratch = self._scratch / scratch_subdir / str(disc_id)
        self._db.execute("UPDATE discs SET scratch_dir = ? WHERE id = ?", (str(scratch), disc_id))
        disc = self.get(disc_id)
        assert disc is not None
        return disc

    def get(self, disc_id: int) -> DiscRecord | None:
        row = self._db.execute(f"SELECT {_COLS} FROM discs WHERE id = ?", (disc_id,)).fetchone()
        return self._record(row) if row else None

    def list(self, status: DiscStatus, include_dismissed: bool = False,
             types: Collection[DiscType] | None = None) -> list[DiscRecord]:
        """Records in `status`, newest first; only `types` if given."""
        rows = self._db.execute(
            f"SELECT {_COLS} FROM discs WHERE status = ? AND (? OR dismissed = 0) "
            "ORDER BY id DESC", (status.value, include_dismissed)).fetchall()
        recs = [self._record(r) for r in rows]
        return [r for r in recs if types is None or r.disc_type in types]

    def set_titles(self, disc_id: int, titles: Iterable[TitleRecord], skipped_short: int,
                   skipped_duplicates: int) -> None:
        self._db.execute("DELETE FROM titles WHERE disc_id = ?", (disc_id,))
        for t in titles:
            self._db.execute(
                "INSERT INTO titles (disc_id, number, makemkv_id, duration_s, size_bytes, audio, "
                "subtitles, segments, file, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (disc_id, t.number, t.makemkv_id, t.duration_s, t.size_bytes, t.audio,
                 t.subtitles, t.segments, t.file, str(t.status)))
        self._db.execute("UPDATE discs SET skipped_short = ?, skipped_duplicates = ? WHERE id = ?",
                         (skipped_short, skipped_duplicates, disc_id))

    def set_title_status(self, disc_id: int, number: int, status: TitleStatus) -> None:
        self._db.execute("UPDATE titles SET status = ? WHERE disc_id = ? AND number = ?",
                         (str(status), disc_id, number))

    def mark_ripped(self, disc_id: int) -> None:
        self._db.execute("UPDATE discs SET status = 'ripped', finished_at = ? WHERE id = ?",
                         (self._ts(), disc_id))

    def mark_failed(self, disc_id: int, failure: Failure) -> None:
        """Fail the record and delete its partial scratch files (idempotent)."""
        rec = self.get(disc_id)
        if rec is None:
            return
        shutil.rmtree(rec.scratch_dir, ignore_errors=True)
        self._db.execute(
            "UPDATE discs SET status = 'failed', failure_kind = ?, failure_headline = ?, "
            "failure_advice = ?, finished_at = COALESCE(finished_at, ?) WHERE id = ?",
            (failure.kind.value, failure.headline, failure.advice, self._ts(), disc_id))
        self._db.execute("UPDATE titles SET status = 'failed' WHERE disc_id = ? "
                         "AND status = 'ripping'", (disc_id,))

    def dismiss(self, disc_id: int) -> None:
        self._db.execute("UPDATE discs SET dismissed = 1 WHERE id = ?", (disc_id,))

    def log(self, disc_id: int, text: str, error: bool = False) -> None:
        self._db.execute("INSERT INTO disc_log (disc_id, at, error, text) VALUES (?, ?, ?, ?)",
                         (disc_id, self._ts(), int(error), text))

    def log_lines(self, disc_id: int) -> list[LogLine]:
        rows = self._db.execute(
            "SELECT at, error, text FROM disc_log WHERE disc_id = ? ORDER BY id",
            (disc_id,)).fetchall()
        return [LogLine(datetime.fromisoformat(a), bool(e), t) for a, e, t in rows]
