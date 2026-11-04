"""Running external programs. Everything that shells out takes a `Runner` (or a
`Streamer` for long jobs), so tests can pass a fake instead of spawning real processes."""

from __future__ import annotations

import codecs
import re
import subprocess
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
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


class Streamer(Protocol):
    """Run a long job, calling `on_line` for each output line as it arrives.

    Returns the exit code. If `on_line` raises, the process is killed and the
    exception propagates (that is how a caller aborts a running job).
    """

    def __call__(self, args: Sequence[str], on_line: Callable[[str], None],
                 cwd: Path | None = None) -> int: ...


def stream(args: Sequence[str], on_line: Callable[[str], None], cwd: Path | None = None) -> int:
    """The real `Streamer`: no console window, no timeout, never logs `args`.

    Lines end at `\\n` or `\\r` (progress meters redraw with `\\r`). stdout and
    stderr are combined. Blocks until exit; call it from a worker thread.
    """
    p = subprocess.Popen(
        list(args),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        cwd=cwd,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        assert p.stdout is not None
        for line in split_lines(iter(lambda: p.stdout.read1(65536), b"")):
            on_line(line)
        return p.wait()
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()


def split_lines(chunks: Iterable[bytes]) -> Iterator[str]:
    """Decode a byte stream into lines split on `\\r` or `\\n`, dropping empty ones."""
    buf = ""
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    for chunk in chunks:
        buf += decoder.decode(chunk)
        *lines, buf = re.split(r"[\r\n]", buf)
        yield from (ln for ln in lines if ln.strip())
    buf += decoder.decode(b"", final=True)
    if buf.strip():
        yield buf
