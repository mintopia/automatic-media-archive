"""Waiting for things outside AMA (network, NAS, tools), shared by the archivers."""

from __future__ import annotations

import time
from collections.abc import Callable, Hashable


class RetryLater(Exception):
    """Something outside AMA isn't available yet; try this step again later."""


class Backoff:
    """Per-key retry times: a step that hit RetryLater waits `retry_seconds` before its
    next try, and is reported once per run of failures, not on every try."""

    def __init__(self, retry_seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.retry_seconds = retry_seconds
        self._clock = clock
        self._not_before: dict[Hashable, float] = {}
        self._failing: set[Hashable] = set()

    def due(self, key: Hashable) -> bool:
        return self._clock() >= self._not_before.get(key, 0.0)

    def later(self, key: Hashable) -> bool:
        """Put `key` off; True if this starts a run of failures (so say why, once)."""
        self._not_before[key] = self._clock() + self.retry_seconds
        first = key not in self._failing
        self._failing.add(key)
        return first

    def done(self, key: Hashable) -> None:
        self._not_before.pop(key, None)
        self._failing.discard(key)
