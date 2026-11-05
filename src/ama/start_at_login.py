"""Start at login (ADR 0009): AMA is a per-user app, not a service, so "start at
login" is a value under HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run that
starts `ama run` with pythonw (no console). Needs no admin rights. The tray's
"Start at login" item toggles it; the Run key is the OS seam (`RunKey`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

NAME = "Automatic Media Archive"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


class RunKey(Protocol):
    def get(self, name: str) -> str | None: ...
    def set(self, name: str, value: str) -> None: ...
    def delete(self, name: str) -> None: ...


class WindowsRunKey:
    """The current user's Run key (winreg; Windows only)."""

    def get(self, name: str) -> str | None:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                value, _ = winreg.QueryValueEx(key, name)
        except FileNotFoundError:
            return None
        return value if isinstance(value, str) else None

    def set(self, name: str, value: str) -> None:
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)

    def delete(self, name: str) -> None:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, name)
        except FileNotFoundError:
            pass


def command_line(python: Path, config: Path) -> str:
    """`ama run` for this install and config, with pythonw when there is one."""
    pythonw = python.with_name("pythonw.exe")
    exe = pythonw if pythonw.exists() else python
    return f'"{exe}" -m ama run --config "{config}"'


class StartAtLogin:
    """On = the Run entry starts this install with this config; an entry left by
    another install counts as off, and turning it on replaces it."""

    def __init__(self, key: RunKey, command: str) -> None:
        self._key = key
        self._command = command

    @property
    def enabled(self) -> bool:
        return self._key.get(NAME) == self._command

    def enable(self) -> None:
        if not self.enabled:
            self._key.set(NAME, self._command)

    def disable(self) -> None:
        self._key.delete(NAME)
