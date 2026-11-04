"""Fakes for the hardware/OS/process boundary. Tests never touch real devices."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

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


class FakeFetch:
    """A `Fetch` (download) that serves bytes from a dict and records the URLs asked for."""

    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files
        self.calls: list[str] = []
        self._once: dict[str, bytes | Exception] = {}

    def serve_once(self, url: str, data: bytes) -> None:
        self._once[url] = data

    def fail_once(self, url: str, error: Exception) -> None:
        self._once[url] = error

    def __call__(self, url: str, dest: Path, progress: Callable[[int, int | None], None]) -> None:
        self.calls.append(url)
        data = self._once.pop(url, None)
        if data is None:
            data = self.files[url]
        if isinstance(data, Exception):
            dest.write_bytes(b"part")
            raise data
        half = len(data) // 2
        dest.write_bytes(data[:half])
        progress(half, len(data))
        dest.write_bytes(data)
        progress(len(data), len(data))


class FakeRunner:
    """A `Runner` that records commands and answers from a handler."""

    def __init__(self, handler: Callable[[Sequence[str]], ProcResult] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.handler = handler or (lambda args: ProcResult(0, ""))

    def __call__(self, args: Sequence[str]) -> ProcResult:
        self.calls.append(list(args))
        return self.handler(args)
