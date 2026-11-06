"""`ama run`: launch the server and relaunch it when it asks to restart (ADR 0009).

The server asks by exiting with RESTART_EXIT_CODE; any other exit (a clean
stop, a config error, a crash) ends the supervisor with that code, so a crash
is never taken for a restart and whatever started `ama run` (Task Scheduler's
restart settings) decides what happens next. A Linux container uses the same
contract through its restart policy instead of this loop.

On Windows `ama run` also shows the tray icon (`ama.tray`); its Quit asks the
server to stop and ends the supervisor with 0. Only one `ama run` goes at a time
(`ama.single_instance`): a second opens the running one's UI and ends with 0.
"""

from __future__ import annotations

import logging
import os
import secrets
import subprocess
import sys
import threading
import webbrowser
from collections.abc import Callable
from pathlib import Path

import httpx

from ama.config import SETUP_HOST, ConfigError, WebConfig, load_config
from ama.settings import upgrade
from ama.single_instance import LOCK_FILE, AlreadyRunning, InstanceLock
from ama.start_at_login import StartAtLogin, WindowsRunKey, command_line
from ama.tray import CONTROL_ENV, ServerControl, Tray, local_urls, make_icon

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


class ServerProcess:
    """`python -m ama serve --config CONFIG` as a child, told the tray's control token.
    Ctrl+C reaches the child too (same console); `launch` waits for it to finish
    shutting down. After `quit()` nothing is started again."""

    def __init__(self, config: Path, token: str,
                 popen: Callable[..., subprocess.Popen] = subprocess.Popen) -> None:
        self._command = [sys.executable, "-m", "ama", "serve", "--config", str(config)]
        self._env = os.environ | {CONTROL_ENV: token}
        self._popen = popen
        self._lock = threading.Lock()
        self._child: subprocess.Popen | None = None
        self.quitting = False

    def launch(self) -> int:
        with self._lock:
            if self.quitting:
                return 0
            self._child = child = self._popen(self._command, env=self._env)
        while True:
            try:
                return child.wait()
            except KeyboardInterrupt:
                continue

    def quit(self, ask: Callable[[], None] = lambda: None, grace: float = 15.0) -> None:
        """Stop the server for good: `ask` it to shut down, and if it hasn't within
        `grace` seconds, terminate it."""
        with self._lock:
            self.quitting = True
            child = self._child
        if child is None:
            return
        ask()
        try:
            child.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            log.warning("server didn't stop within %.0f s; terminating it", grace)
            child.terminate()


def _addresses(config: Path, upgrade_first: bool) -> tuple[str, str] | None:
    """(where the tray reaches the server, its UI address) for `config`: Setup's on
    localhost with no file yet (ADR 0016); None if the file can't be read."""
    if not config.exists():
        return local_urls(SETUP_HOST, WebConfig().port)
    try:
        if upgrade_first:  # the file the child is about to read
            upgrade(config)
        web = load_config(config).web
    except ConfigError:
        return None
    return local_urls(web.host, web.port)


def run(config: Path, platform: str = sys.platform,
        popen: Callable[..., subprocess.Popen] = subprocess.Popen) -> int:
    """`ama run`: supervise the server, with the tray icon on Windows. Returns the exit
    code to end with (0 after Quit, or when another `ama run` already goes)."""
    try:
        lock = InstanceLock.acquire(config.parent / LOCK_FILE)
    except AlreadyRunning:
        log.info("AMA is already running; opening it")
        _, ui_url = _addresses(config, upgrade_first=False) or local_urls(
            SETUP_HOST, WebConfig().port)
        webbrowser.open(ui_url)
        return 0
    with lock:
        return _supervise_with_tray(config, platform, popen)


def _supervise_with_tray(config: Path, platform: str,
                         popen: Callable[..., subprocess.Popen]) -> int:
    token = secrets.token_hex(16)
    server = ServerProcess(config, token, popen)
    http = httpx.Client(timeout=5)
    control = ServerControl(http, token)
    quit_requested = threading.Event()

    def quit() -> None:  # from the tray's thread: close the menu now, stop the server after
        quit_requested.set()
        if icon is not None:
            icon.stop()

    tray = Tray(control, StartAtLogin(WindowsRunKey(), command_line(Path(sys.executable), config)),
                ui_url="", open_url=webbrowser.open, quit=quit)

    def launch() -> int:
        # where the child will listen; an unreadable file: the child reports it and exits
        if (addresses := _addresses(config, upgrade_first=True)) is not None:
            http.base_url, tray.ui_url = addresses
        return server.launch()

    try:
        icon = make_icon(tray, platform)
    except Exception:  # no notification area (e.g. no desktop session): run without one
        log.exception("couldn't show the tray icon")
        icon = None
    if icon is None:
        return supervise(launch)
    codes: list[int] = []

    def supervise_then_close() -> None:
        codes.append(supervise(launch))
        icon.stop()

    supervisor = threading.Thread(target=supervise_then_close, daemon=True)
    supervisor.start()
    icon.run()  # until Quit, or until the server stops for good
    if quit_requested.is_set():
        server.quit(ask=control.quit)
    supervisor.join()
    return 0 if quit_requested.is_set() else codes[0]
