"""The supervisor's tray icon (ADR 0009): Open AMA, Pause/Resume new Discs, Restart,
Start at login, Quit.

The tray lives in `ama run`, the server in its child `ama serve`, so the tray drives
the server over HTTP like the UI does (`ServerControl`). The supervisor hands the
child a random token in CONTROL_ENV; the server lets requests carrying it in
CONTROL_HEADER past the password, so the tray works with `web.password` set.
Pause lives in the server (kept in SQLite): the tray polls it, so a Pause made in
the UI shows in the menu and one made in the tray shows in the UI (over SSE).

`Tray` is the menu as data and its actions; `make_icon` puts it on screen with
pystray, Windows only. Nothing here imports pystray off Windows.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from ama.start_at_login import StartAtLogin
from ama.web.auth import CONTROL_HEADER

log = logging.getLogger(__name__)

CONTROL_ENV = "AMA_CONTROL_TOKEN"
POLL_SECONDS = 2.0


class ServerControl:
    """The running server, as the tray sees it. Every call copes with the server being
    down or restarting: reads give None, actions do nothing."""

    def __init__(self, http: httpx.Client, token: str) -> None:
        self._http = http
        self._headers = {CONTROL_HEADER: token}

    def _post(self, path: str) -> None:
        try:
            self._http.post(path, headers=self._headers, follow_redirects=False)
        except httpx.HTTPError as e:
            log.info("tray: %s failed: %s", path, e)

    def paused(self) -> bool | None:
        """Whether AMA is Paused; None when the server can't be asked."""
        try:
            r = self._http.get("/control", headers=self._headers, follow_redirects=False)
        except httpx.HTTPError:
            return None
        return bool(r.json()["paused"]) if r.status_code == 200 else None

    def set_paused(self, paused: bool) -> None:
        self._post("/pause" if paused else "/resume")

    def restart(self) -> None:
        """Restart once nothing Rips or Encodes (the UI's "Restart when idle")."""
        self._post("/restart/when-idle")

    def quit(self) -> None:
        """Shut the server down without restarting."""
        self._post("/control/quit")


def local_urls(host: str, port: int) -> tuple[str, str]:
    """(where the tray reaches the server, the UI address it opens) for `web.host/port`."""
    if host in ("0.0.0.0", "::", ""):
        return f"http://127.0.0.1:{port}", f"http://localhost:{port}/"
    return f"http://{host}:{port}", f"http://{host}:{port}/"


@dataclass(frozen=True)
class MenuItem:
    label: str
    action: Callable[[], None]
    enabled: bool = True
    checked: bool = False


class Tray:
    def __init__(self, control: ServerControl, login: StartAtLogin, ui_url: str,
                 open_url: Callable[[str], object], quit: Callable[[], None]) -> None:
        self._control = control
        self._login = login
        self.ui_url = ui_url
        self._open_url = open_url
        self._quit = quit
        self._paused: bool | None = None  # None: the server isn't answering (yet)

    def refresh(self) -> bool:
        """Ask the server again; True when the menu changed."""
        paused = self._control.paused()
        changed = paused != self._paused
        self._paused = paused
        return changed

    def items(self) -> list[MenuItem]:
        up = self._paused is not None
        return [
            MenuItem("Open AMA", self.open_ui),
            MenuItem("Resume new Discs" if self._paused else "Pause new Discs",
                     self.toggle_pause, enabled=up),
            MenuItem("Restart", self.restart, enabled=up),
            MenuItem("Start at login", self.toggle_start_at_login,
                     checked=self._login.enabled),
            MenuItem("Quit", self.quit),
        ]

    def open_ui(self) -> None:
        self._open_url(self.ui_url)

    def toggle_pause(self) -> None:
        paused = self._control.paused()  # the UI may have changed it since the last poll
        if paused is not None:
            self._control.set_paused(not paused)
        self.refresh()

    def restart(self) -> None:
        self._control.restart()

    def toggle_start_at_login(self) -> None:
        if self._login.enabled:
            self._login.disable()
        else:
            self._login.enable()

    def quit(self) -> None:
        self._quit()


def _disc_image():
    """A Disc in DESIGN.md's ink and filed-teal, drawn at 64 px (Windows scales it)."""
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((2, 2, 61, 61), fill="#17181A")
    draw.ellipse((14, 14, 49, 49), fill="#1F7A74")
    draw.ellipse((26, 26, 37, 37), fill=(0, 0, 0, 0))
    return image


class TrayIcon:
    """`Tray` on screen with pystray (Windows). `run()` blocks on the calling thread
    until `stop()`; a thread polls the server so the menu follows the UI."""

    def __init__(self, tray: Tray) -> None:
        import pystray

        self._tray = tray
        self._stopped = threading.Event()

        def menu_item(i: int) -> pystray.MenuItem:
            def item() -> MenuItem:
                return tray.items()[i]

            def act(icon: pystray.Icon, _item: object) -> None:
                item().action()
                icon.update_menu()

            return pystray.MenuItem(lambda _: item().label, act, default=i == 0,
                                    enabled=lambda _: item().enabled,
                                    checked=lambda _: item().checked)

        menu = pystray.Menu(*(menu_item(i) for i in range(len(tray.items()))))
        self._icon = pystray.Icon("ama", _disc_image(), "Automatic Media Archive", menu)

    def _poll(self) -> None:
        while not self._stopped.wait(POLL_SECONDS):
            if self._tray.refresh():
                self._icon.update_menu()

    def run(self) -> None:
        def setup(icon) -> None:
            icon.visible = True
            if self._tray.refresh():
                icon.update_menu()
            threading.Thread(target=self._poll, daemon=True).start()

        self._icon.run(setup)

    def stop(self) -> None:
        self._stopped.set()
        self._icon.stop()


def make_icon(tray: Tray, platform: str) -> TrayIcon | None:
    """The tray icon on Windows; None elsewhere (no tray, no pystray)."""
    if platform != "win32":
        return None
    return TrayIcon(tray)
