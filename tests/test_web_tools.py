"""What the UI says about tools: download progress/failures, and MakeMKV problems."""

import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ama.app import create_app
from ama.tools import PINS, ToolPending, ToolReady
from tests.conftest import eventually, make_harness
from tests.fakes import FakeFetch

DATA = Path(__file__).parent / "data"
TOO_OLD = (DATA / "makemkvcon-info-too-old.txt").read_text(encoding="utf-8")
FFMPEG_URL = PINS[0].url
CYANRIP_URL = PINS[1].url


class BlockingFetch(FakeFetch):
    """Reports some progress on ffmpeg, then holds until released; cyanrip fails."""

    def __init__(self) -> None:
        super().__init__({})
        self.release = threading.Event()

    def __call__(self, url, dest, progress):
        self.calls.append(url)
        if url == CYANRIP_URL:
            raise OSError("getaddrinfo failed")
        progress(120_000_000, 257_736_868)
        self.release.wait(5)
        raise OSError("cancelled")


@pytest.fixture
def blocked(tmp_path):
    fetch = BlockingFetch()
    h = make_harness(tmp_path, fetch=fetch)
    with TestClient(create_app(h.services)) as c:
        try:
            yield h, c, fetch
        finally:
            fetch.release.set()


def test_download_progress_shows_on_now_page(blocked):
    h, c, fetch = blocked
    eventually(lambda: fetch.calls)
    eventually(lambda: "120" in c.get("/").text)
    page = c.get("/").text
    assert "Getting ffmpeg 9.0.2" in page and "120 / 258 MB" in page
    assert "Encodes wait" in page


def test_failed_download_names_what_waits_and_the_retry(blocked):
    h, c, fetch = blocked
    fetch.release.set()
    eventually(lambda: "getaddrinfo failed" in c.get("/").text)
    page = c.get("/").text
    assert "Couldn't download cyanrip 0.9.3.1" in page
    assert "CD Rips wait" in page


def test_no_tool_notices_when_everything_is_ready(client, harness):
    eventually(lambda: isinstance(harness.services.tools.status("makemkvcon"), ToolReady))
    page = client.get("/").text
    assert "MakeMKV" not in page and "Getting" not in page


@pytest.mark.parametrize("output,key,expect", [
    ("", "T-x", ["Can't find MakeMKV", "https://www.makemkv.com/download/", "[tools] makemkvcon"]),
    (TOO_OLD, "", ["MakeMKV v1.18.2 is too old", "https://www.makemkv.com/download/"]),
    (None, "", ["MakeMKV isn't registered", "Help → Register",
                "https://forum.makemkv.com/forum/viewtopic.php?t=1053"]),
])
def test_each_makemkv_problem_has_its_own_fix(tmp_path, output, key, expect):
    h = make_harness(tmp_path)
    h.makemkv["key"] = key
    if output is not None:
        h.makemkv["output"] = output
    if output == "":
        (tmp_path / "MakeMKV" / "makemkvcon64.exe").unlink()
    with TestClient(create_app(h.services)) as c:
        eventually(lambda: not isinstance(h.services.tools.status("makemkvcon"),
                                          (ToolReady, ToolPending)))
        now = c.get("/").text
        assert "DVD and Blu-ray Rips are paused" in now and 'href="/makemkv"' in now
        page = c.get("/makemkv").text
        for text in expect:
            assert text in page, text
        assert "CDs still work" in page
        assert "I've fixed it, check again" in page


def test_check_again_rechecks_makemkv(tmp_path):
    h = make_harness(tmp_path)
    h.makemkv["key"] = ""
    with TestClient(create_app(h.services)) as c:
        eventually(lambda: "isn't registered" in c.get("/makemkv").text)
        h.makemkv["key"] = "T-fixed"
        r = c.post("/makemkv/check", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/makemkv"
        page = c.get("/makemkv").text
        assert "MakeMKV v2.0.0 is ready" in page
        assert "paused" not in c.get("/").text
