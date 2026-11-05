"""The supervisor's tray menu (ADR 0009): Open AMA, Pause/Resume, Restart, Start at login,
Quit. The tray drives the running server over HTTP, so Pause stays in step with the UI."""

from __future__ import annotations

import sys

import httpx
import pytest
from fastapi.testclient import TestClient

from ama.app import create_app
from ama.start_at_login import StartAtLogin
from ama.tray import ServerControl, Tray, local_urls
from tests.conftest import eventually, make_harness
from tests.test_start_at_login import CMD, FakeRunKey

TOKEN = "control-token"


@pytest.fixture
def server(harness, client):
    """The server, the tray's view of it, and a browser on the UI (no password set)."""
    yield harness, ServerControl(client, TOKEN), client


class Spy:
    def __init__(self) -> None:
        self.opened: list[str] = []
        self.quit = 0


def _tray(control, key=None, spy=None) -> Tray:
    spy = spy or Spy()
    return Tray(control, StartAtLogin(key or FakeRunKey(), CMD), ui_url="http://localhost:8080/",
                open_url=spy.opened.append, quit=lambda: setattr(spy, "quit", spy.quit + 1))


def _labels(tray: Tray) -> dict[str, tuple[bool, bool]]:
    """label -> (enabled, checked)"""
    return {i.label: (i.enabled, i.checked) for i in tray.items()}


def test_pause_from_the_tray_shows_in_the_ui_and_the_other_way_round(server):
    h, control, browser = server
    tray = _tray(control)
    assert "Pause new Discs" in _labels(tray)

    tray.toggle_pause()
    assert h.services.pause.paused
    assert 'formaction="/pause" aria-pressed="true"' in browser.get("/").text
    assert _labels(tray)["Resume new Discs"] == (True, False)

    browser.post("/resume", headers={"referer": "/"})
    assert tray.refresh()
    assert "Pause new Discs" in _labels(tray)
    assert not tray.refresh()  # nothing new


def test_restart_from_the_tray_restarts_once_nothing_rips_or_encodes(server):
    h, control, _ = server
    stopped: list[bool] = []
    h.services.restart.on_request = lambda: stopped.append(True)
    _tray(control).restart()
    eventually(lambda: stopped == [True])


def test_open_quit_and_start_at_login(server):
    _, control, _ = server
    key, spy = FakeRunKey(), Spy()
    tray = _tray(control, key, spy)
    assert _labels(tray)["Start at login"] == (True, False)

    tray.toggle_start_at_login()
    assert _labels(tray)["Start at login"] == (True, True) and key.values
    tray.toggle_start_at_login()
    assert _labels(tray)["Start at login"] == (True, False) and not key.values

    tray.open_ui()
    tray.quit()
    assert spy.opened == ["http://localhost:8080/"] and spy.quit == 1
    assert [i.label for i in tray.items()] == [
        "Open AMA", "Pause new Discs", "Restart", "Start at login", "Quit"]


def test_with_a_password_only_the_supervisors_token_gets_in(tmp_path):
    h = make_harness(tmp_path, password="hunter2")
    with TestClient(create_app(h.services, control_token=TOKEN), follow_redirects=False) as c:
        for token in ("", "wrong"):
            control = ServerControl(c, token)
            assert control.paused() is None
            control.set_paused(True)
            assert not h.services.pause.paused
        control = ServerControl(c, TOKEN)
        assert control.paused() is False
        control.set_paused(True)
        assert h.services.pause.paused and control.paused() is True
        assert c.get("/").status_code == 303  # the token is the tray's, not a sign-in


def test_only_the_supervisor_can_quit_the_server(tmp_path):
    h = make_harness(tmp_path)  # no password: the UI is open, Quit still isn't
    stopped: list[bool] = []
    h.services.restart.on_request = lambda: stopped.append(True)
    for app_token, token in ((TOKEN, ""), (TOKEN, "wrong"), ("", "")):
        with TestClient(create_app(h.services, control_token=app_token)) as c:
            assert c.post("/control/quit", headers={"X-AMA-Control": token}).status_code == 403
    with TestClient(create_app(h.services, control_token=TOKEN)) as c:
        ServerControl(c, TOKEN).quit()
    assert stopped == [True] and not h.services.restart.requested  # exits 0, not 75


def test_ama_serve_on_its_own_accepts_no_token(tmp_path):
    h = make_harness(tmp_path, password="hunter2")
    with TestClient(create_app(h.services), follow_redirects=False) as c:
        assert ServerControl(c, "").paused() is None


def test_a_server_that_is_down_or_restarting_greys_out_its_items():
    def down(request):
        raise httpx.ConnectError("refused")

    control = ServerControl(httpx.Client(base_url="http://127.0.0.1:1",
                                         transport=httpx.MockTransport(down)), TOKEN)
    tray = _tray(control)
    tray.refresh()
    labels = _labels(tray)
    assert labels["Pause new Discs"] == (False, False)
    assert labels["Restart"] == (False, False)
    assert labels["Open AMA"][0] and labels["Quit"][0] and labels["Start at login"][0]
    tray.toggle_pause()  # does nothing, raises nothing
    tray.restart()


@pytest.mark.parametrize("host, control, ui", [
    ("0.0.0.0", "http://127.0.0.1:8080", "http://localhost:8080/"),
    ("::", "http://127.0.0.1:8080", "http://localhost:8080/"),
    ("192.168.1.20", "http://192.168.1.20:8080", "http://192.168.1.20:8080/"),
])
def test_where_the_tray_finds_the_server(host, control, ui):
    assert local_urls(host, 8080) == (control, ui)


def test_runs_off_windows_have_no_tray_and_never_import_one(monkeypatch):
    from ama import tray

    monkeypatch.delitem(sys.modules, "pystray", raising=False)
    assert tray.make_icon(_tray(None), platform="linux") is None
    assert "pystray" not in sys.modules


class FakePystray:
    """Enough of pystray's API to drive `TrayIcon` without a real notification icon."""

    class MenuItem:
        def __init__(self, text, action, default=False, enabled=True, checked=None):
            self.text, self.action, self.default = text, action, default
            self.enabled, self.checked = enabled, checked

    class Menu:
        def __init__(self, *items):
            self.items = items

    class Icon:
        def __init__(self, name, image, title, menu):
            self.image, self.title, self.menu = image, title, menu
            self.updates = 0
            self.visible = False

        def update_menu(self):
            self.updates += 1

        def run(self, setup):
            setup(self)

        def stop(self):
            pass


def _shown(icon) -> list[tuple[str, bool, bool]]:
    return [(i.text(i), i.enabled(i), i.checked(i)) for i in icon.menu.items]


def test_the_windows_icon_shows_the_menu_and_follows_the_ui(server, monkeypatch):
    h, control, browser = server
    monkeypatch.setitem(sys.modules, "pystray", FakePystray)
    monkeypatch.setattr("ama.tray.POLL_SECONDS", 0.01)
    key = FakeRunKey()
    from ama.tray import make_icon

    tray_icon = make_icon(_tray(control, key), platform="win32")
    icon = tray_icon._icon
    assert icon.title == "Automatic Media Archive" and icon.image.size == (64, 64)
    tray_icon.run()  # fake: returns after setup, leaving the poller running
    try:
        assert icon.visible and _shown(icon)[1] == ("Pause new Discs", True, False)
        assert icon.menu.items[0].default  # double-click opens AMA

        start_at_login = icon.menu.items[3]
        start_at_login.action(icon, start_at_login)
        assert key.values and _shown(icon)[3] == ("Start at login", True, True)

        browser.post("/pause", headers={"referer": "/"})  # paused in the UI
        eventually(lambda: _shown(icon)[1] == ("Resume new Discs", True, False))
        updates = icon.updates
        pause = icon.menu.items[1]
        pause.action(icon, pause)  # resumed in the tray
        assert not h.services.pause.paused and icon.updates > updates
    finally:
        tray_icon.stop()
