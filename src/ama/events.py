"""In-process pub/sub of *topics* (`Topic`).

Publishers only say "topic X changed"; each SSE connection re-renders the
fragment for that topic from current state. Events therefore carry no payload,
can't go stale, and a reconnecting browser just re-renders everything.
Call `publish` from the event loop thread.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from enum import StrEnum


class Topic(StrEnum):
    """What changed; each names the UI fragments that re-render (web.FRAGMENTS)."""

    DRIVE = "drive"      # the drive card
    TOOLS = "tools"
    RIP = "rip"          # a Rip, and the Ripping bin
    ENCODE = "encode"    # the Encode queue
    ARCHIVED = "archived"      # History
    REVIEW = "review"    # the Review queue
    SCRATCH = "scratch"
    PAUSE = "pause"      # Paused or accepting new Discs: the top-bar mark and menu
    PROBLEMS = "problems"  # Now page banners; a Job's Waiting line (problems.py)
    LOGS = "logs"        # a Run or Step changed, or a running Step has new output (runs.py)
    UPDATE = "update"    # a newer AMA Release was found (updates.py): the Now notice


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[str]] = set()

    def publish(self, topic: Topic) -> None:
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
