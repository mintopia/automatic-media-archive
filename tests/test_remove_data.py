"""Uninstall's "also remove settings and history": `ama remove-data` deletes
%LOCALAPPDATA%\\AMA and never touches a Library (#75, ADR 0017)."""

from __future__ import annotations

from pathlib import Path

import pytest

import ama.__main__ as main


@pytest.fixture
def data(tmp_path, monkeypatch) -> Path:
    """A stand-in %LOCALAPPDATA%\\AMA holding what AMA leaves there."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    monkeypatch.delenv("AMA_CONFIG", raising=False)
    data = tmp_path / "LocalAppData" / "AMA"
    (data / "logs").mkdir(parents=True)
    (data / "logs" / "ama.log").write_text("started\n", encoding="utf-8")
    (data / "tools" / "ffmpeg").mkdir(parents=True)
    (data / "tools" / "ffmpeg" / "ffmpeg.exe").write_bytes(b"MZ")
    (data / "ama.sqlite3").write_bytes(b"SQLite format 3\0")
    _settings(data, [])
    return data


def _settings(data: Path, library_paths: list[Path]) -> None:
    entries = "".join(
        f'\n[[libraries]]\nname = "L{i}"\nkind = "films"\npath = \'{p}\'\ndefault = {str(i == 0).lower()}\n'
        for i, p in enumerate(library_paths)
    )
    (data / "ama.toml").write_text(f"[paths]\nscratch = 'scratch'\n{entries}", encoding="utf-8")


def _remove_data() -> int:
    with pytest.raises(SystemExit) as stopped:
        main.main(["remove-data"])
    return stopped.value.code


def test_it_removes_settings_history_logs_and_tools(data):
    assert _remove_data() == 0
    assert not data.exists()
    assert data.parent.exists()


def test_with_nothing_to_remove_it_succeeds(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("AMA_CONFIG", raising=False)
    assert _remove_data() == 0


def test_a_library_inside_the_data_folder_is_kept(data):
    films = data / "media" / "Films"
    (films / "Heat (1995)").mkdir(parents=True)
    (films / "Heat (1995)" / "Heat (1995).mkv").write_bytes(b"film")
    (data / "media" / "notes.txt").write_text("AMA's", encoding="utf-8")
    _settings(data, [films])

    assert _remove_data() == 0

    assert (films / "Heat (1995)" / "Heat (1995).mkv").read_bytes() == b"film"
    assert sorted(p.name for p in data.rglob("*")) == sorted(
        ["media", "Films", "Heat (1995)", "Heat (1995).mkv"])


def test_when_the_data_folder_is_inside_a_library_nothing_is_removed(data, capsys):
    _settings(data, [data.parent])

    assert _remove_data() == 1

    assert (data / "ama.toml").exists() and (data / "ama.sqlite3").exists()
    assert str(data) in capsys.readouterr().err


def test_unreadable_settings_remove_nothing_because_the_libraries_are_unknown(data, capsys):
    (data / "ama.toml").write_text("[paths\n", encoding="utf-8")

    assert _remove_data() == 1

    assert (data / "ama.sqlite3").exists()
    assert "ama.toml" in capsys.readouterr().err
