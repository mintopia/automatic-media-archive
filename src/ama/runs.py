"""Runs and Steps (GLOSSARY): the record Logs shows of every tool run.

A Run is a Job's record of its Steps (one per Job), or an app event (startup, NAS,
tools) with Steps of its own. Each Step keeps its output: stored line by line, and
held in a ring of recent lines while it runs, so a page can follow it live (topic
`logs`, at most twice a second). Callers pass only output text, never command lines;
known secrets are masked on the way in all the same.

Thread-safe: tools' output arrives from worker threads.
"""

from __future__ import annotations

import asyncio
import collections
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from ama.db import Database
from ama.events import EventBus, Topic

PUBLISH_EVERY_SECONDS = 0.5
STOPPED = "AMA stopped before this finished"


class RunKind(StrEnum):
    JOB = "job"
    APP = "app"      # startup
    NAS = "nas"      # the NAS dropped, or came back
    TOOLS = "tools"  # a tool download or check after startup


class StepState(StrEnum):
    """What a stored Step is doing. A Job's page adds waiting and not-run Steps of its own."""

    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass(frozen=True)
class RunRecord:
    id: int
    kind: RunKind
    job_id: int | None
    item: str
    title: str
    detail: str
    started_at: datetime
    finished_at: datetime | None
    failed: bool | None  # None while running

    @property
    def took(self) -> timedelta | None:
        return self.finished_at - self.started_at if self.finished_at else None


@dataclass(frozen=True)
class StepRecord:
    id: int
    run_id: int
    key: str
    name: str
    subject: str
    tool: str
    result: str
    state: StepState
    exit_code: int | None
    started_at: datetime
    finished_at: datetime | None
    lines: int
    errors: int

    @property
    def took(self) -> timedelta | None:
        return self.finished_at - self.started_at if self.finished_at else None


@dataclass(frozen=True)
class OutputLine:
    n: int  # 1-based line number in the Step's output
    at: datetime
    error: bool
    text: str


_RUN_COLS = "id, kind, job_id, item, title, detail, started_at, finished_at, failed"
_STEP_COLS = ("s.id, s.run_id, s.key, s.name, s.subject, s.tool, s.result, s.state, s.exit_code, "
              "s.started_at, s.finished_at, "
              "(SELECT COUNT(*) FROM step_lines l WHERE l.step_id = s.id), "
              "(SELECT COUNT(*) FROM step_lines l WHERE l.step_id = s.id AND l.error)")


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class Runs:
    RING = 1000  # recent lines held per running Step

    def __init__(self, db: Database, bus: EventBus,
                 secrets: Callable[[], Iterable[str]] = lambda: (),
                 now: Callable[[], datetime] = datetime.now) -> None:
        self._db = db
        self._bus = bus
        self._secrets = secrets
        self._now = now
        self._lock = threading.Lock()
        self._ring: dict[int, collections.deque[OutputLine]] = {}
        self._count: dict[int, int] = {}
        self._open: dict[int, int] = {}  # Job id -> its running Step
        self._loop: asyncio.AbstractEventLoop | None = None
        self._pending = False
        self._last_publish = 0.0

    def _ts(self) -> str:
        return self._now().isoformat(timespec="seconds")

    # --- Runs ---

    def start_run(self, kind: RunKind, title: str, item: str = "", detail: str = "") -> int:
        cur = self._db.execute(
            "INSERT INTO runs (kind, item, title, detail, started_at) VALUES (?, ?, ?, ?, ?)",
            (kind.value, item, title, detail, self._ts()))
        assert cur.lastrowid is not None
        self._changed()
        return cur.lastrowid

    def finish_run(self, run_id: int, failed: bool, title: str | None = None,
                   detail: str | None = None) -> None:
        self._db.execute(
            "UPDATE runs SET finished_at = ?, failed = ?, title = COALESCE(?, title), "
            "detail = COALESCE(?, detail) WHERE id = ?",
            (self._ts(), int(failed), title, detail, run_id))
        self._changed()

    def update_run(self, run_id: int, title: str | None = None,
                   detail: str | None = None) -> None:
        self._db.execute("UPDATE runs SET title = COALESCE(?, title), "
                         "detail = COALESCE(?, detail) WHERE id = ?", (title, detail, run_id))
        self._changed()

    def job_run(self, job_id: int) -> int:
        """The Job's one Run, made the first time it's asked for."""
        self._db.execute("INSERT OR IGNORE INTO runs (kind, job_id, started_at) "
                         "VALUES ('job', ?, COALESCE((SELECT started_at FROM jobs WHERE id = ?), ?))",
                         (job_id, job_id, self._ts()))
        return self._db.execute("SELECT id FROM runs WHERE job_id = ?", (job_id,)).fetchone()[0]

    def get_run(self, run_id: int) -> RunRecord | None:
        row = self._db.execute(f"SELECT {_RUN_COLS} FROM runs WHERE id = ?",
                               (run_id,)).fetchone()
        return self._run(row) if row else None

    def list_runs(self, kinds: Iterable[RunKind] | None = None, limit: int = 200,
                  before: datetime | None = None) -> list[RunRecord]:
        """Newest first; only `kinds` if given; only runs started before `before` if given."""
        wanted = [k.value for k in (kinds or RunKind)]
        rows = self._db.execute(
            f"SELECT {_RUN_COLS} FROM runs WHERE kind IN ({','.join('?' * len(wanted))}) "
            "AND (? IS NULL OR started_at < ?) ORDER BY started_at DESC, id DESC LIMIT ?",
            (*wanted, before and before.isoformat(), before and before.isoformat(),
             limit)).fetchall()
        return [self._run(r) for r in rows]

    def later_fix(self, run: RunRecord) -> RunRecord | None:
        """The first Run after `run` that ended well for the same thing (a failed app event's
        "fixed by")."""
        row = self._db.execute(
            f"SELECT {_RUN_COLS} FROM runs WHERE id > ? AND failed = 0 AND kind != 'job' "
            "AND (item = ? OR id IN (SELECT run_id FROM steps WHERE key IN "
            "(SELECT key FROM steps WHERE run_id = ? AND state = 'failed') AND state = 'done')) "
            "ORDER BY id LIMIT 1", (run.id, run.item, run.id)).fetchone()
        return self._run(row) if row else None

    @staticmethod
    def _run(row) -> RunRecord:
        id_, kind, job_id, item, title, detail, started, finished, failed = row
        return RunRecord(id_, RunKind(kind), job_id, item, title, detail, _dt(started),  # type: ignore[arg-type]
                         _dt(finished), None if failed is None else bool(failed))

    # --- Steps ---

    def begin(self, run_id: int, key: str, name: str, tool: str = "",
              subject: str = "") -> int:
        """Start (or start again, with fresh output) the Run's Step `key`."""
        ts = self._ts()
        self._db.execute(
            "INSERT INTO steps (run_id, key, position, name, subject, tool, state, started_at) "
            "VALUES (?, ?, (SELECT COUNT(*) FROM steps WHERE run_id = ?), ?, ?, ?, 'running', ?) "
            "ON CONFLICT (run_id, key) DO UPDATE SET name = excluded.name, "
            "subject = excluded.subject, tool = excluded.tool, result = '', state = 'running', "
            "exit_code = NULL, started_at = excluded.started_at, finished_at = NULL",
            (run_id, key, run_id, name, subject, tool, ts))
        step_id = self._db.execute("SELECT id FROM steps WHERE run_id = ? AND key = ?",
                                   (run_id, key)).fetchone()[0]
        self._db.execute("DELETE FROM step_lines WHERE step_id = ?", (step_id,))
        with self._lock:
            self._ring[step_id] = collections.deque(maxlen=self.RING)
            self._count[step_id] = 0
        self._changed()
        return step_id

    def line(self, step_id: int, text: str, error: bool = False) -> None:
        """One line of the Step's output (progress-only lines are the caller's to leave out)."""
        for secret in self._secrets():
            if secret:
                text = text.replace(secret, "•••")
        at = self._now().replace(microsecond=0)
        self._db.execute("INSERT INTO step_lines (step_id, at, error, text) VALUES (?, ?, ?, ?)",
                         (step_id, at.isoformat(), int(error), text))
        with self._lock:
            ring = self._ring.get(step_id)
            if ring is not None:
                self._count[step_id] += 1
                ring.append(OutputLine(self._count[step_id], at, error, text))
        self._changed()

    def end(self, step_id: int, failed: bool = False, exit_code: int | None = None,
            result: str | None = None) -> None:
        self._db.execute(
            "UPDATE steps SET state = ?, exit_code = COALESCE(?, exit_code), "
            "result = COALESCE(?, result), finished_at = ? WHERE id = ? AND state = 'running'",
            ("failed" if failed else "done", exit_code, result, self._ts(), step_id))
        with self._lock:
            self._ring.pop(step_id, None)
            self._count.pop(step_id, None)
        self._changed()

    def set_result(self, step_id: int, result: str) -> None:
        self._db.execute("UPDATE steps SET result = ? WHERE id = ?", (result, step_id))
        self._changed()

    def steps(self, run_id: int) -> list[StepRecord]:
        rows = self._db.execute(f"SELECT {_STEP_COLS} FROM steps s WHERE s.run_id = ? "
                                "ORDER BY s.position", (run_id,)).fetchall()
        return [self._step(r) for r in rows]

    def get_step(self, step_id: int) -> StepRecord | None:
        row = self._db.execute(f"SELECT {_STEP_COLS} FROM steps s WHERE s.id = ?",
                               (step_id,)).fetchone()
        return self._step(row) if row else None

    @staticmethod
    def _step(row) -> StepRecord:
        (id_, run_id, key, name, subject, tool, result, state, code, started, finished,
         lines, errors) = row
        return StepRecord(id_, run_id, key, name, subject, tool, result, StepState(state), code,
                          _dt(started), _dt(finished), lines, errors)  # type: ignore[arg-type]

    def output(self, step_id: int) -> list[OutputLine]:
        """All of the Step's stored output."""
        rows = self._db.execute("SELECT at, error, text FROM step_lines WHERE step_id = ? "
                                "ORDER BY id", (step_id,)).fetchall()
        return [OutputLine(n, datetime.fromisoformat(a), bool(e), t)
                for n, (a, e, t) in enumerate(rows, 1)]

    def tail(self, step_id: int) -> list[OutputLine]:
        """A running Step's recent lines (up to RING) from memory; else its stored output."""
        with self._lock:
            ring = self._ring.get(step_id)
            if ring is not None:
                return list(ring)
        return self.output(step_id)[-self.RING:]

    def running(self, step_id: int) -> bool:
        with self._lock:
            return step_id in self._ring

    # --- a Job's Steps, one after another ---

    def job_begin(self, job_id: int, key: str, name: str, tool: str = "",
                  subject: str = "") -> int:
        """Start the Job's Step `key`; the Step before it, if still running, is done."""
        with self._lock:
            previous = self._open.pop(job_id, None)
        if previous is not None:
            self.end(previous)
        step = self.begin(self.job_run(job_id), key, name, tool, subject)
        with self._lock:
            self._open[job_id] = step
        return step

    def job_note(self, job_id: int, text: str, error: bool = False) -> None:
        """A line for whichever of the Job's Steps is running (none: not kept in Logs)."""
        with self._lock:
            step = self._open.get(job_id)
        if step is not None:
            self.line(step, text, error)

    def job_step(self, job_id: int) -> int | None:
        with self._lock:
            return self._open.get(job_id)

    def job_end(self, job_id: int, failed: bool = False, exit_code: int | None = None,
                result: str | None = None, finish: bool = False) -> None:
        """End the Job's running Step; `finish` also ends its Run (Filed or Failed)."""
        with self._lock:
            step = self._open.pop(job_id, None)
        if step is not None:
            self.end(step, failed, exit_code, result)
        if finish:
            self.finish_run(self.job_run(job_id), failed)

    # --- lifecycle ---

    def recover(self) -> None:
        """At startup: an app event cut short by the restart failed; a Job's running Step
        carries on (its worker picks the Job up again, or fails it)."""
        rows = self._db.execute(
            "SELECT s.id, r.kind, r.job_id FROM steps s JOIN runs r ON r.id = s.run_id "
            "WHERE s.state = 'running'").fetchall()
        for step_id, kind, job_id in rows:
            if kind == RunKind.JOB:
                with self._lock:
                    self._open[job_id] = step_id
                    self._ring[step_id] = collections.deque(
                        (ln for ln in self.output(step_id)[-self.RING:]), maxlen=self.RING)
                    self._count[step_id] = len(self.output(step_id))
            else:
                self._db.execute("UPDATE steps SET state = 'failed', result = ?, "
                                 "finished_at = COALESCE(finished_at, started_at) WHERE id = ?",
                                 (STOPPED, step_id))
        self._db.execute("UPDATE runs SET failed = 1, finished_at = started_at "
                         "WHERE kind != 'job' AND finished_at IS NULL")

    async def run(self) -> None:
        """Background task: remembers the loop, so lines from worker threads can publish."""
        self._loop = asyncio.get_running_loop()
        await asyncio.Event().wait()

    def _changed(self) -> None:
        """Publish `logs` soon: from any thread, at most every PUBLISH_EVERY_SECONDS, and
        always once after the last change."""
        try:
            loop = asyncio.get_running_loop()
            self._loop = loop
        except RuntimeError:
            loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(self._schedule, loop)
        except RuntimeError:  # the loop closed meanwhile
            pass

    def _schedule(self, loop: asyncio.AbstractEventLoop) -> None:
        if self._pending:
            return
        self._pending = True
        wait = max(0.0, self._last_publish + PUBLISH_EVERY_SECONDS - time.monotonic())
        loop.call_later(wait, self._fire)

    def _fire(self) -> None:
        self._pending = False
        self._last_publish = time.monotonic()
        self._bus.publish(Topic.LOGS)
