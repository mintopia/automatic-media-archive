"""Running external programs. Everything that shells out takes a `Runner`,
so tests can pass a fake instead of spawning real processes."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ProcResult:
    returncode: int
    output: str  # stdout and stderr combined


class Runner(Protocol):
    def __call__(self, args: Sequence[str]) -> ProcResult: ...


class LineRunner(Protocol):
    """Run a long job, calling `on_line` for each output line as it arrives.

    Returns the exit code. If `on_line` raises, the process is killed and the
    exception propagates (that is how a caller aborts a running job).
    """

    def __call__(self, args: Sequence[str], on_line: Callable[[str], None]) -> int: ...


def stream(args: Sequence[str], on_line: Callable[[str], None]) -> int:
    """Blocking; call from a worker thread. No console window, no timeout, never logs `args`."""
    p = subprocess.Popen(
        list(args),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        assert p.stdout is not None
        for line in p.stdout:
            on_line(line.rstrip("\r\n"))
        return p.wait()
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()


def run(args: Sequence[str]) -> ProcResult:
    """Run to completion with no console window. Never logs `args` (may hold secrets)."""
    p = subprocess.run(
        list(args),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        timeout=120,
    )
    return ProcResult(p.returncode, p.stdout)
