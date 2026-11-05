"""The app's log file never gets request URLs (a TMDB v3 key travels in the URL)."""

from __future__ import annotations

import logging

from ama.__main__ import _setup_logging


def test_http_request_urls_are_not_logged(tmp_path):
    root = logging.getLogger()
    before = root.level
    root.setLevel(logging.INFO)  # as the app runs (basicConfig is a no-op under pytest)
    try:
        _setup_logging(tmp_path / "logs" / "ama.log")
        assert not logging.getLogger("httpx").isEnabledFor(logging.INFO)
        assert not logging.getLogger("httpcore").isEnabledFor(logging.INFO)
    finally:
        root.setLevel(before)
        for name in ("httpx", "httpcore"):
            logging.getLogger(name).setLevel(logging.NOTSET)


def test_a_config_that_wont_load_under_pythonw_says_why_in_a_message_box(tmp_path, monkeypatch):
    import sys

    import pytest

    import ama.__main__ as main
    shown: list[tuple[str, str]] = []
    monkeypatch.setattr(sys, "stderr", None)  # pythonw: no console
    monkeypatch.setattr(main, "_message_box", lambda title, text: shown.append((title, text)))
    config = tmp_path / "ama.toml"
    config.write_text("[web]\nport = 'eighty'\n", encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        main.serve(config)
    assert e.value.code == 2
    log = (tmp_path / "ama-startup-error.log").read_text(encoding="utf-8")
    assert "web.port" in log
    [(title, text)] = shown
    assert "AMA" in title and "web.port" in text and "ama-startup-error.log" in text
