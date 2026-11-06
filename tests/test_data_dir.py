"""Settings, database and logs live in %LOCALAPPDATA%\\AMA unless told otherwise (#70, ADR 0017)."""

from __future__ import annotations

import sys
from contextlib import nullcontext
from pathlib import Path

import pytest

import ama.__main__ as main


@pytest.fixture
def local_app_data(tmp_path, monkeypatch) -> Path:
    """A stand-in %LOCALAPPDATA%: the tests never touch the real one."""
    base = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(base))
    monkeypatch.delenv("AMA_CONFIG", raising=False)
    return base


@pytest.fixture
def started(monkeypatch) -> list[Path]:
    """The config each command was started with."""
    configs: list[Path] = []
    monkeypatch.setattr(main, "run", lambda config: configs.append(config) or 0)
    monkeypatch.setattr(main, "serve", configs.append)
    return configs


@pytest.mark.parametrize("command", [[], ["serve"]])
def test_with_no_config_given_ama_uses_the_one_in_local_app_data(local_app_data, started,
                                                                  command):
    with pytest.raises(SystemExit) if not command else nullcontext():
        main.main(command)
    [config] = started
    assert config.resolve() == (local_app_data / "AMA" / "ama.toml").resolve()


def test_ama_config_overrides_the_default(local_app_data, started, monkeypatch, tmp_path):
    monkeypatch.setenv("AMA_CONFIG", str(tmp_path / "elsewhere.toml"))
    main.main(["serve"])
    assert started == [tmp_path / "elsewhere.toml"]


def test_config_flag_overrides_ama_config(local_app_data, started, monkeypatch, tmp_path):
    monkeypatch.setenv("AMA_CONFIG", str(tmp_path / "elsewhere.toml"))
    main.main(["serve", "--config", str(tmp_path / "mine.toml")])
    assert started == [tmp_path / "mine.toml"]


def test_startup_error_under_pythonw_is_logged_in_the_data_folder_even_before_it_exists(
        local_app_data, monkeypatch):
    monkeypatch.setattr(sys, "stderr", None)  # pythonw: no console
    shown: list[str] = []
    monkeypatch.setattr(main, "_message_box", lambda title, text: shown.append(text))
    config = local_app_data / "AMA" / "ama.toml"
    with pytest.raises(SystemExit):
        main.serve(config)
    log = local_app_data / "AMA" / "ama-startup-error.log"
    assert "No config file" in log.read_text(encoding="utf-8")
    assert str(log) in shown[0]


def test_tools_download_into_the_same_folder(local_app_data):
    from ama.tools import default_tools_dir
    assert default_tools_dir() == local_app_data / "AMA" / "tools"

