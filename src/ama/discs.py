"""Disc records: every Disc we started to Rip, its Titles, its log, how it ended.

Persisted in SQLite (`discs`, `titles`, `disc_log`) so a failure and its log
survive a restart, and so a Rip cut short by a restart can be cleaned up.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
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
    LICENCE = "licence"  # MakeMKV refused to work: not the Disc's fault
    MAKEMKV = "makemkv"  # MakeMKV missing, or crashed
    DISC = "disc"  # couldn't read the Disc, or nothing on it to rip
    TITLE = "title"  # a Title couldn't be ripped
    INTERRUPTED = "interrupted"  # the app stopped mid-Rip


@dataclass(frozen=True)
class Failure:
    kind: FailureKind
    headline: str
    advice: str


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
    at: str  # HH:MM:SS
    error: bool
    text: str

    def __str__(self) -> str:
        return f"{self.at}  {self.text}"


@dataclass(frozen=True)
class DiscRecord:
    id: int
    disc_type: DiscType
    label: str
    status: DiscStatus
    failure: Failure | None
    scratch_dir: Path
    skipped_short: int
    skipped_duplicates: int
    started_at: datetime
    finished_at: datetime | None
    dismissed: bool
    titles: tuple[TitleRecord, ...]

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


class DiscStore:
    def __init__(self, db: Database, now: Callable[[], datetime] = datetime.now) -> None:
        self._db = db
        self._now = now

    def _ts(self) -> str:
        return self._now().isoformat(timespec="seconds")

    def create(self, disc_type: DiscType, label: str, scratch_root: Path) -> DiscRecord:
        """New Disc in `ripping`; its scratch dir is `scratch_root/<id>`."""
        cur = self._db.execute(
            "INSERT INTO discs (disc_type, label, status, scratch_dir, started_at) "
            "VALUES (?, ?, 'ripping', '', ?)", (str(disc_type), label, self._ts()))
        disc_id = cur.lastrowid
        assert disc_id is not None
        self._db.execute("UPDATE discs SET scratch_dir = ? WHERE id = ?",
                         (str(scratch_root / str(disc_id)), disc_id))
        disc = self.get(disc_id)
        assert disc is not None
        return disc

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

    def finish(self, disc_id: int) -> None:
        self._db.execute("UPDATE discs SET status = 'ripped', finished_at = ? WHERE id = ?",
                         (self._ts(), disc_id))

    def fail(self, disc_id: int, failure: Failure) -> None:
        self._db.execute(
            "UPDATE discs SET status = 'failed', failure = ?, failure_headline = ?, "
            "failure_advice = ?, finished_at = ? WHERE id = ?",
            (str(failure.kind), failure.headline, failure.advice, self._ts(), disc_id))
        self._db.execute("UPDATE titles SET status = 'failed' WHERE disc_id = ? "
                         "AND status = 'ripping'", (disc_id,))

    def dismiss(self, disc_id: int) -> None:
        self._db.execute("UPDATE discs SET dismissed = 1 WHERE id = ?", (disc_id,))

    def log(self, disc_id: int, text: str, error: bool = False) -> None:
        self._db.execute("INSERT INTO disc_log (disc_id, at, error, text) VALUES (?, ?, ?, ?)",
                         (disc_id, self._ts(), int(error), text))

    def log_lines(self, disc_id: int) -> list[LogLine]:
        rows = self._db.execute(
            "SELECT at, error, text FROM disc_log WHERE disc_id = ? ORDER BY id", (disc_id,))
        return [LogLine(datetime.fromisoformat(at).strftime("%H:%M:%S"), bool(e), t)
                for at, e, t in rows.fetchall()]

    def get(self, disc_id: int) -> DiscRecord | None:
        row = self._db.execute(
            "SELECT id, disc_type, label, status, failure, failure_headline, failure_advice, "
            "scratch_dir, skipped_short, skipped_duplicates, started_at, finished_at, dismissed "
            "FROM discs WHERE id = ?", (disc_id,)).fetchone()
        if row is None:
            return None
        titles = self._db.execute(
            "SELECT number, makemkv_id, duration_s, size_bytes, audio, subtitles, segments, file, "
            "status FROM titles WHERE disc_id = ? ORDER BY number", (disc_id,)).fetchall()
        (id_, dtype, label, status, kind, headline, advice, scratch, short, dupes, started,
         finished, dismissed) = row
        return DiscRecord(
            id=id_, disc_type=DiscType(dtype), label=label, status=DiscStatus(status),
            failure=Failure(FailureKind(kind), headline, advice) if kind else None,
            scratch_dir=Path(scratch), skipped_short=short, skipped_duplicates=dupes,
            started_at=datetime.fromisoformat(started),
            finished_at=datetime.fromisoformat(finished) if finished else None,
            dismissed=bool(dismissed),
            titles=tuple(TitleRecord(*t[:8], status=TitleStatus(t[8])) for t in titles),
        )

    def _ids(self, where: str) -> list[DiscRecord]:
        rows = self._db.execute(f"SELECT id FROM discs WHERE {where} ORDER BY id").fetchall()
        return [d for (i,) in rows if (d := self.get(i))]

    def interrupted(self) -> list[DiscRecord]:
        return self._ids("status = 'ripping'")

    def unseen_failure(self) -> DiscRecord | None:
        """The most recent failed Disc nobody has dismissed yet."""
        failed = self._ids("status = 'failed' AND dismissed = 0")
        return failed[-1] if failed else None
