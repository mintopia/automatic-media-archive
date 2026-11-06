"""One `ama run` at a time: a lock file next to the settings file (the data folder, so one
per Windows user, by default). A second launch (the Start menu while AMA already runs from
sign-in) finds it held and opens the running AMA instead of starting another on the same
database and drive.

The operating system holds the lock for the process, so it goes when AMA does, even after a
crash: there's no stale lock file to clear.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import IO, Self

LOCK_FILE = "ama.lock"


class AlreadyRunning(Exception):
    """Another process holds the lock."""


def _lock(f: IO[bytes]) -> None:
    """Take `f`'s lock without waiting; OSError if another handle has it."""
    if sys.platform == "win32":
        import msvcrt
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(f: IO[bytes]) -> None:
    if sys.platform == "win32":
        import msvcrt
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)


class InstanceLock:
    """Held from `acquire` until `release` (or the end of a `with` block, or the process)."""

    def __init__(self, file: IO[bytes]) -> None:
        self._file = file

    @classmethod
    def acquire(cls, path: Path) -> Self:
        """Take the lock at `path`; raises AlreadyRunning if another holder has it."""
        path.parent.mkdir(parents=True, exist_ok=True)
        f = open(path, "a+b")  # never truncated: the holder's handle stays as it was
        try:
            _lock(f)
        except OSError:
            f.close()
            raise AlreadyRunning(path) from None
        return cls(f)

    def release(self) -> None:
        if self._file.closed:
            return
        try:
            _unlock(self._file)
        finally:
            self._file.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()
