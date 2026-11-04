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
