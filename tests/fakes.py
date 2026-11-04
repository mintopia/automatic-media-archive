"""Fakes for the hardware/OS/process boundary. Tests never touch real devices."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from ama.drive import DiscPresent, DiscType, DriveEmpty, DriveState
from ama.proc import ProcResult


class FakeDrive:
    """A `DriveProbe` whose contents the test controls."""

    def __init__(self) -> None:
        self.state: DriveState = DriveEmpty()
        self._error: Exception | None = None

    def insert(self, disc_type: DiscType, label: str = "") -> None:
        self.state = DiscPresent(disc_type, label)

    def eject(self) -> None:
        self.state = DriveEmpty()

    def fail_with(self, error: Exception) -> None:
        self._error = error

    def probe(self) -> DriveState:
        if self._error:
            raise self._error
        return self.state


class FakeRunner:
    """A `Runner` that records commands and answers from a handler."""

    def __init__(self, handler: Callable[[Sequence[str]], ProcResult] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.handler = handler or (lambda args: ProcResult(0, ""))

    def __call__(self, args: Sequence[str]) -> ProcResult:
        self.calls.append(list(args))
        return self.handler(args)
