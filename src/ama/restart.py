"""Restarting AMA from the UI (ADR 0009): the server exits with RESTART_EXIT_CODE and
whatever supervises it (`ama run`, a container's restart policy) starts it again.

`Restarter.now()` asks for the exit; `__main__` hooks `on_request` up to the
web server. `when_idle()` waits instead until nothing Rips or Encodes, and
meanwhile `holding()` tells the rippers to start no new Rip and the Encoder to
start no new Encode, so the wait can end.
"""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import Callable
from dataclasses import dataclass

from ama.events import EventBus, Topic


@dataclass(frozen=True)
class Busy:
    """What a restart would cut off."""

    rip: str | None = None  # the Disc being ripped, by name
    encodes: int = 0
    eta_s: int | None = None  # until both are done, when known

    def __bool__(self) -> bool:
        return self.rip is not None or self.encodes > 0

    @property
    def headline(self) -> str:
        """'A Rip and an Encode are running'."""
        if self.rip is not None and self.encodes:
            return "A Rip and an Encode are running"
        return "A Rip is running" if self.rip is not None else "An Encode is running"

    @property
    def stops(self) -> str:
        """What 'Restart now' does to them."""
        if self.rip is not None and self.encodes:
            return ("stops both: the Rip has to start again with the Disc reinserted, "
                    "and the Encode starts over from the beginning")
        if self.rip is not None:
            return "stops it: the Rip has to start again with the Disc reinserted"
        return "stops it: the Encode starts over from the beginning"


class Restarter:
    def __init__(self, busy: Callable[[], Busy], bus: EventBus, interval: float = 1.0) -> None:
        self.busy = busy
        self._bus = bus
        self._interval = interval
        self.boot = secrets.token_hex(8)  # tells a reconnecting page it's a new server
        self.requested = False
        self.waiting = False
        self.on_request: Callable[[], None] = lambda: None

    def holding(self) -> bool:
        """Start no new Rip or Encode: AMA is about to restart."""
        return self.waiting or self.requested

    def now(self) -> None:
        if self.requested:
            return
        self.requested, self.waiting = True, False
        self.on_request()

    def when_idle(self) -> None:
        self.waiting = True
        self._bus.publish(Topic.DRIVE)

    def cancel(self) -> None:
        """Don't restart after all: held Discs and Encodes go ahead."""
        self.waiting = False
        self._bus.publish(Topic.DRIVE)  # the video ripper looks at the drive again

    async def run(self) -> None:
        while True:
            if self.waiting and not self.busy():
                self.now()
            await asyncio.sleep(self._interval)
