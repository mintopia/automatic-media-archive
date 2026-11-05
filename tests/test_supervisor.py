"""`ama run`: the supervisor relaunches the server only when it asks to restart (ADR 0009)."""

from __future__ import annotations

import subprocess
import sys
import threading

from ama.supervisor import RESTART_EXIT_CODE, ServerProcess, run, supervise
from ama.tray import CONTROL_ENV
from tests.conftest import eventually


def _launches(*codes: int):
    calls: list[int] = []

    def launch() -> int:
        calls.append(len(calls))
        return codes[len(calls) - 1]

    return launch, calls


def test_a_restart_request_relaunches_the_server():
    launch, calls = _launches(RESTART_EXIT_CODE, RESTART_EXIT_CODE, 0)
    assert supervise(launch) == 0
    assert len(calls) == 3


def test_a_crash_is_not_mistaken_for_a_restart_request():
    for crash in (1, 2, -1073741819, 3221225477):  # exception, config error, Windows access violation
        launch, calls = _launches(crash, 0)
        assert supervise(launch) == crash
        assert len(calls) == 1


class FakeChild:
    """A `subprocess.Popen` of `ama serve` that exits with the codes it's given."""

    def __init__(self, codes: list[int]) -> None:
        self.codes = codes
        self.started: list[tuple[list[str], dict]] = []
        self.terminated = 0
        self.exit_code = 0  # what a HANG child exits with once stopped
        self._exit: threading.Event | None = None

    def __call__(self, args, env=None):
        self.started.append((list(args), dict(env or {})))
        self._exit = threading.Event()
        return self

    def wait(self, timeout: float | None = None) -> int:
        if timeout is not None:  # the supervisor waiting for a Quit to land
            if not self._exit.wait(timeout):
                raise subprocess.TimeoutExpired("ama serve", timeout)
            return 0
        if self.codes[0] == HANG:
            self._exit.wait()
            self.codes.pop(0)
            return self.exit_code
        return self.codes.pop(0)

    def stop(self) -> None:
        """The server shutting down when asked."""
        self._exit.set()

    def terminate(self) -> None:
        self.terminated += 1
        self._exit.set()


HANG = -999  # runs until terminated


def test_the_server_gets_its_config_and_the_trays_token(tmp_path):
    child = FakeChild([RESTART_EXIT_CODE, 0])
    server = ServerProcess(tmp_path / "ama.toml", token="t0k", popen=child)
    assert supervise(server.launch) == 0
    (args, env), again = child.started
    assert args[-4:] == ["ama", "serve", "--config", str(tmp_path / "ama.toml")]
    assert env[CONTROL_ENV] == "t0k" and again[1][CONTROL_ENV] == "t0k"


def _supervising(server):
    result: list[int] = []
    t = threading.Thread(target=lambda: result.append(supervise(server.launch)))
    t.start()
    return t, result


def test_quit_asks_the_server_to_stop_and_it_is_not_started_again(tmp_path):
    child = FakeChild([HANG, 0])
    server = ServerProcess(tmp_path / "ama.toml", token="t", popen=child)
    t, result = _supervising(server)
    eventually(lambda: child.started)
    server.quit(ask=child.stop)
    t.join(5)
    assert result and child.terminated == 0 and len(child.started) == 1
    assert server.launch() == 0 and len(child.started) == 1  # a late restart starts nothing


def test_a_server_that_ignores_quit_is_terminated(tmp_path):
    child = FakeChild([HANG])
    server = ServerProcess(tmp_path / "ama.toml", token="t", popen=child)
    t, _ = _supervising(server)
    eventually(lambda: child.started)
    server.quit(grace=0.05)
    t.join(5)
    assert child.terminated == 1 and not t.is_alive()


def test_off_windows_ama_run_has_no_tray(tmp_path, monkeypatch):
    monkeypatch.delitem(sys.modules, "pystray", raising=False)
    child = FakeChild([3])
    assert run(tmp_path / "ama.toml", platform="linux", popen=child) == 3
    assert "pystray" not in sys.modules


class FakeIcon:
    """The tray icon: `run` blocks until `stop`, like pystray's."""

    def __init__(self, tray) -> None:
        self.tray = tray
        self.running = threading.Event()
        self._stopped = threading.Event()

    def run(self) -> None:
        self.running.set()
        self._stopped.wait()

    def stop(self) -> None:
        self._stopped.set()

    def click(self, label: str) -> None:
        next(i for i in self.tray.items() if i.label == label).action()


def _run_with_tray(tmp_path, monkeypatch, child):
    icons: list[FakeIcon] = []
    monkeypatch.setattr("ama.supervisor.make_icon",
                        lambda tray, platform: icons.append(FakeIcon(tray)) or icons[0])
    monkeypatch.setattr("ama.tray.ServerControl.quit", lambda self: child.stop())
    result: list[int] = []
    t = threading.Thread(target=lambda: result.append(
        run(tmp_path / "ama.toml", platform="win32", popen=child)))
    t.start()
    eventually(lambda: icons and icons[0].running.is_set() and child.started)
    return icons[0], t, result


def test_quit_in_the_tray_stops_the_server_and_ends_ama_run(tmp_path, monkeypatch):
    child = FakeChild([HANG, 0])
    icon, t, result = _run_with_tray(tmp_path, monkeypatch, child)
    icon.click("Quit")
    t.join(5)
    assert result == [0] and child.terminated == 0 and len(child.started) == 1


def test_a_server_that_stops_for_good_closes_the_tray(tmp_path, monkeypatch):
    child = FakeChild([HANG])
    icon, t, result = _run_with_tray(tmp_path, monkeypatch, child)
    child.exit_code = 1
    child.stop()  # a crash: no restart asked for
    t.join(5)
    assert result == [1] and not t.is_alive()
