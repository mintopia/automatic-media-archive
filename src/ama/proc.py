"""Running external programs. Everything that shells out takes a `Runner`,
so tests can pass a fake instead of spawning real processes."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ProcResult:
    returncode: int
    output: str  # stdout and stderr combined


class Runner(Protocol):
    def __call__(self, args: Sequence[str]) -> ProcResult: ...


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
