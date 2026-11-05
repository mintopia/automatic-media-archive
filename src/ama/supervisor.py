"""`ama run`: launch the server and relaunch it when it asks to restart (ADR 0009).

The server asks by exiting with RESTART_EXIT_CODE; any other exit (a clean
stop, a config error, a crash) ends the supervisor with that code, so a crash
is never taken for a restart and whatever started `ama run` (Task Scheduler's
restart settings) decides what happens next. A Linux container uses the same
contract through its restart policy instead of this loop.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from collections.abc import Callable, Sequence

log = logging.getLogger(__name__)

RESTART_EXIT_CODE = 75  # EX_TEMPFAIL: "try again"


def supervise(launch: Callable[[], int]) -> int:
    """Run `launch` (start the server, wait, return its exit code) until it stops asking
    to restart; return the exit code it stopped with."""
    while True:
        code = launch()
        if code != RESTART_EXIT_CODE:
            return code
        log.info("server asked to restart; relaunching")


def server_launcher(args: Sequence[str]) -> Callable[[], int]:
    """Start `python -m ama serve ARGS` as a child and wait for it. Ctrl+C reaches the
    child too (same console); the supervisor waits for it to finish shutting down."""
    command = [sys.executable, "-m", "ama", "serve", *args]

    def launch() -> int:
        child = subprocess.Popen(command)
        while True:
            try:
                return child.wait()
            except KeyboardInterrupt:
                continue

    return launch
