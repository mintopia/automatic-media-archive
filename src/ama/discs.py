"""Disc records: one row per Disc AMA Ripped (or tried to), shared by CD and video Rips.

A record is `ripping` while the Rip runs, then `ripped` or `failed`. A failed
record keeps its log for the UI until the user dismisses it; its partial
scratch files are already gone.
"""

from __future__ import annotations

import shutil
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


@dataclass(frozen=True)
class Failure:
    kind: str       # machine-readable, e.g. "unreadable_track"
    headline: str   # one sentence: what went wrong
    advice: str     # what the user can do about it


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


@dataclass(frozen=True)
class LogLine:
    at: datetime
    error: bool
    text: str


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


_COLS = ("id, disc_type, label, status, failure_kind, failure_headline, failure_advice, "
         "scratch_dir, started_at, finished_at, dismissed")


def _record(row) -> DiscRecord:
    (id_, dtype, label, status, fkind, fhead, fadv, scratch, started, finished, dismissed) = row
    return DiscRecord(
        id=id_, disc_type=DiscType(dtype), label=label, status=DiscStatus(status),
        failure=Failure(fkind, fhead or "", fadv or "") if fkind else None,
        scratch_dir=Path(scratch), started_at=datetime.fromisoformat(started),
        finished_at=datetime.fromisoformat(finished) if finished else None,
        dismissed=bool(dismissed),
    )


class Discs:
    def __init__(self, db: Database, scratch: Path) -> None:
        self._db = db
        self._scratch = scratch

    def create(self, disc_type: DiscType, label: str, scratch_subdir: str) -> DiscRecord:
        """Start a record in `ripping`; its scratch folder is `scratch/<subdir>/<id>`."""
        cur = self._db.execute(
            "INSERT INTO discs (disc_type, label, status, scratch_dir, started_at) "
            "VALUES (?, ?, 'ripping', '', ?)", (disc_type.value, label, _now()))
        disc_id = cur.lastrowid
        scratch = self._scratch / scratch_subdir / str(disc_id)
        self._db.execute("UPDATE discs SET scratch_dir = ? WHERE id = ?", (str(scratch), disc_id))
        return self.get(disc_id)  # type: ignore[return-value]

    def get(self, disc_id: int) -> DiscRecord | None:
        row = self._db.execute(f"SELECT {_COLS} FROM discs WHERE id = ?", (disc_id,)).fetchone()
        return _record(row) if row else None

    def list(self, status: DiscStatus, include_dismissed: bool = False) -> list[DiscRecord]:
        rows = self._db.execute(
            f"SELECT {_COLS} FROM discs WHERE status = ? AND (? OR dismissed = 0) "
            "ORDER BY id DESC", (status.value, include_dismissed)).fetchall()
        return [_record(r) for r in rows]

    def mark_ripped(self, disc_id: int) -> None:
        self._db.execute("UPDATE discs SET status = 'ripped', finished_at = ? WHERE id = ?",
                         (_now(), disc_id))

    def mark_failed(self, disc_id: int, failure: Failure) -> None:
        """Fail the record and delete its partial scratch files (idempotent)."""
        rec = self.get(disc_id)
        if rec is None:
            return
        shutil.rmtree(rec.scratch_dir, ignore_errors=True)
        self._db.execute(
            "UPDATE discs SET status = 'failed', failure_kind = ?, failure_headline = ?, "
            "failure_advice = ?, finished_at = COALESCE(finished_at, ?) WHERE id = ?",
            (failure.kind, failure.headline, failure.advice, _now(), disc_id))

    def dismiss(self, disc_id: int) -> None:
        self._db.execute("UPDATE discs SET dismissed = 1 WHERE id = ?", (disc_id,))

    def log(self, disc_id: int, text: str, error: bool = False) -> None:
        self._db.execute("INSERT INTO disc_log (disc_id, at, error, text) VALUES (?, ?, ?, ?)",
                         (disc_id, _now(), int(error), text))

    def log_lines(self, disc_id: int) -> list[LogLine]:
        rows = self._db.execute(
            "SELECT at, error, text FROM disc_log WHERE disc_id = ? ORDER BY id",
            (disc_id,)).fetchall()
        return [LogLine(datetime.fromisoformat(a), bool(e), t) for a, e, t in rows]
