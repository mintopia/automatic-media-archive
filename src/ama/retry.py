"""Waiting for things outside AMA (network, NAS, tools), shared by the archivers."""

from __future__ import annotations

import time
from collections.abc import Callable, Hashable
from typing import Any

from ama.problems import Problem, Problems


class RetryLater(Exception):
    """Something outside AMA isn't available yet; try this step again later.
    `problem` names an app-wide cause (a Now page banner), if it is one."""

    def __init__(self, reason: str, problem: Problem | None = None) -> None:
        super().__init__(reason)
        self.problem = problem


class Backoff:
    """Per-key retry times: a step that hit RetryLater waits `retry_seconds` before its
    next try, and is reported once per run of failures, not on every try.
    With `problems`, the reason is kept as the Job's Waiting line (`job` maps a key to
    its Job id) until the step is `done`."""

    def __init__(self, retry_seconds: float, clock: Callable[[], float] = time.monotonic,
                 problems: Problems | None = None,
                 job: Callable[[Any], int] = int) -> None:
        self.retry_seconds = retry_seconds
        self._clock = clock
        self._problems = problems
        self._job = job
        self._not_before: dict[Hashable, float] = {}
        self._failing: set[Hashable] = set()

    def due(self, key: Hashable) -> bool:
        return self._clock() >= self._not_before.get(key, 0.0)

    def later(self, key: Hashable, why: str = "", problem: Problem | None = None) -> bool:
        """Put `key` off because of `why`; True if this starts a run of failures (so say
        why, once)."""
        self._not_before[key] = self._clock() + self.retry_seconds
        first = key not in self._failing
        self._failing.add(key)
        if self._problems is not None and why:
            self._problems.waiting(self._job(key), why, self.retry_seconds, problem)
        return first

    def done(self, key: Hashable) -> None:
        self._not_before.pop(key, None)
        self._failing.discard(key)
        if self._problems is not None:
            self._problems.moved_on(self._job(key))
