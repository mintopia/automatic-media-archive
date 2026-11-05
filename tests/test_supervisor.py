"""`ama run`: the supervisor relaunches the server only when it asks to restart (ADR 0009)."""

from __future__ import annotations

from ama.supervisor import RESTART_EXIT_CODE, supervise


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
