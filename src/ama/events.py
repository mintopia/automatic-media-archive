"""In-process pub/sub of *topics* ("drive", "nas", ...).

Publishers only say "topic X changed"; each SSE connection re-renders the
fragment for that topic from current state. Events therefore carry no payload,
can't go stale, and a reconnecting browser just re-renders everything.
Call `publish` from the event loop thread.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[str]] = set()

    def publish(self, topic: str) -> None:
        for q in self._subscribers:
            q.put_nowait(topic)

    @contextmanager
    def subscribe(self) -> Iterator[asyncio.Queue[str]]:
        q: asyncio.Queue[str] = asyncio.Queue()
        self._subscribers.add(q)
        try:
            yield q
        finally:
            self._subscribers.discard(q)
