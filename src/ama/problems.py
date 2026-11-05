"""Why a Job can't move on to its next Phase, kept where the UI can read it (#40).

Two kinds: a Job's *Waiting* (its current RetryLater reason and when it's tried
again; sub-detail inside its Phase, never a Phase of its own), and app-wide
*problems* shown as Now page banners. A banner comes either from Jobs waiting on
an app-wide cause (`Waiting.problem`, e.g. no TMDB key) or from a component that
`report`s one (Plex, notifications) until it `resolved`s it.

Tool readiness has its own live state and banner (`tools.html`); it isn't
repeated here. A waiting cause's `detail` (which Library
folder) shows on its banner.
"""

from __future__ import annotations

import asyncio
import threading
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from ama.events import EventBus, Topic


class Problem(StrEnum):
    """An app-wide reason Jobs can't move on; `partials/problems.html` words each."""

    TMDB_KEY = "tmdb_key"  # [tmdb] api_key empty while video Jobs wait to be identified
    PLEX = "plex"          # the last Plex scan request failed
    NOTIFY = "notify"      # the last notification couldn't be sent
    LIBRARY_FOLDER = "library_folder"  # a Library folder a Job files to isn't reachable


@dataclass(frozen=True)
class Waiting:
    reason: str
    retry_at: datetime
    problem: Problem | None = None
    detail: str = ""


@dataclass(frozen=True)
class Banner:
    problem: Problem
    jobs: int = 0     # Jobs waiting on it (0 for a reported problem)
    detail: str = ""  # what the component said, or the waiting Jobs' details


# A Job's Waiting line shows on its card (Ripping/Encoding bins) and page; banners on Now.
_JOB_TOPICS = (Topic.RIP, Topic.ENCODE, Topic.PROBLEMS)


class Problems:
    def __init__(self, bus: EventBus, now: Callable[[], datetime] = datetime.now) -> None:
        self._bus = bus
        self._now = now
        self._waiting: dict[int, Waiting] = {}
        self._reported: dict[Problem, str] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: int | None = None

    async def run(self) -> None:
        """Background task: remember the loop, so worker threads can report too."""
        self._loop = asyncio.get_running_loop()
        self._loop_thread = threading.get_ident()

    # -- per Job --

    def waiting(self, job_id: int, reason: str, retry_seconds: float,
                problem: Problem | None = None, detail: str = "") -> None:
        """The Job can't move on because of `reason`; it's tried again in `retry_seconds`."""
        self._waiting[job_id] = Waiting(reason, self._now() + timedelta(seconds=retry_seconds),
                                        problem, detail)
        self._publish(*_JOB_TOPICS)

    def moved_on(self, job_id: int) -> None:
        if self._waiting.pop(job_id, None) is not None:
            self._publish(*_JOB_TOPICS)

    def why(self, job_id: int) -> Waiting | None:
        return self._waiting.get(job_id)

    # -- app-wide --

    def report(self, problem: Problem, detail: str) -> None:
        if self._reported.get(problem) != detail:
            self._reported[problem] = detail
            self._publish(Topic.PROBLEMS)

    def resolved(self, problem: Problem) -> None:
        if self._reported.pop(problem, None) is not None:
            self._publish(Topic.PROBLEMS)

    def banners(self) -> list[Banner]:
        jobs = Counter(w.problem for w in self._waiting.values() if w.problem is not None)
        out = [Banner(p, jobs=n, detail=", ".join(sorted(
                   {w.detail for w in self._waiting.values() if w.problem == p and w.detail})))
               for p, n in jobs.items()]
        out += [Banner(p, detail=d) for p, d in self._reported.items() if p not in jobs]
        return sorted(out, key=lambda b: list(Problem).index(b.problem))

    def _publish(self, *topics: Topic) -> None:
        if self._loop is not None and threading.get_ident() != self._loop_thread:
            for t in topics:
                self._loop.call_soon_threadsafe(self._bus.publish, t)
            return
        for t in topics:
            self._bus.publish(t)
