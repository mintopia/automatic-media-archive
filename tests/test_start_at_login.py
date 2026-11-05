"""Start at login (ADR 0009): a per-user Run entry that starts `ama run`, never a service."""

from __future__ import annotations

from pathlib import Path

from ama.start_at_login import NAME, StartAtLogin, command_line


class FakeRunKey:
    """HKCU\\...\\Run as a dict."""

    def __init__(self, **values: str) -> None:
        self.values = dict(values)

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def set(self, name: str, value: str) -> None:
        self.values[name] = value

    def delete(self, name: str) -> None:
        self.values.pop(name, None)


CMD = r'"C:\ama\.venv\Scripts\pythonw.exe" -m ama run --config "C:\ama\ama.toml"'


def test_enabling_and_disabling_start_at_login():
    key = FakeRunKey()
    login = StartAtLogin(key, CMD)
    assert not login.enabled

    login.enable()
    login.enable()  # idempotent
    assert login.enabled and key.values == {NAME: CMD}

    login.disable()
    login.disable()
    assert not login.enabled and key.values == {}


def test_an_entry_for_another_install_counts_as_off_and_enabling_replaces_it():
    key = FakeRunKey(**{NAME: r'"D:\old\pythonw.exe" -m ama run --config "D:\old\ama.toml"'})
    login = StartAtLogin(key, CMD)
    assert not login.enabled
    login.enable()
    assert key.values == {NAME: CMD}


def test_other_run_entries_are_left_alone():
    key = FakeRunKey(OneDrive="onedrive.exe")
    StartAtLogin(key, CMD).enable()
    StartAtLogin(key, CMD).disable()
    assert key.values == {"OneDrive": "onedrive.exe"}


def test_the_command_starts_the_supervisor_without_a_console(tmp_path):
    scripts = tmp_path / "Scripts"
    scripts.mkdir()
    (scripts / "pythonw.exe").write_bytes(b"")
    config = tmp_path / "ama.toml"
    assert command_line(scripts / "python.exe", config) == (
        f'"{scripts / "pythonw.exe"}" -m ama run --config "{config}"')
    # No pythonw next to it (not Windows, or an odd install): use the interpreter as is.
    other = Path(tmp_path / "bin" / "python3")
    assert command_line(other, config).startswith(f'"{other}" -m ama run')
