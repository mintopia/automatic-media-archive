"""What the UI says about tools: download progress/failures, and MakeMKV problems."""

import html
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ama.app import create_app
from ama.tools import PINS, ToolPending, ToolReady
from tests.conftest import eventually, make_harness
from tests.fakes import FakeFetch

DATA = Path(__file__).parent / "data"
TOO_OLD = (DATA / "makemkv-licence-too-old.txt").read_text(encoding="utf-8")
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
    assert f"Couldn't download {PINS[1].label}" in page
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
    h.makemkv_check["key"] = key
    if output is not None:
        h.makemkv_check["output"] = output
    if output == "":
        (tmp_path / "MakeMKV" / "makemkvcon64.exe").unlink()
    with TestClient(create_app(h.services)) as c:
        eventually(lambda: not isinstance(h.services.tools.status("makemkvcon"),
                                          (ToolReady, ToolPending)))
        now = html.unescape(c.get("/").text)
        assert "DVD and Blu-ray Rips are paused" in now and 'href="/makemkv"' in now
        page = html.unescape(c.get("/makemkv").text)
        for text in expect:
            assert text in page, text
        assert "CDs still work" in page
        assert "I've fixed it, check again" in page


@pytest.mark.parametrize("name,waits", [("ffmpeg", "Encodes wait"),
                                        ("ffprobe", "Encodes wait"),
                                        ("cyanrip", "CD Rips wait")])
def test_a_tool_set_in_ama_toml_but_missing_gives_a_banner_until_it_is_there(
        tmp_path, name, waits):
    h = make_harness(tmp_path)
    exe = tmp_path / f"{name}.exe"
    exe.unlink()
    with TestClient(create_app(h.services)) as c:
        now = html.unescape(c.get("/").text)
        assert f"Can't find {name}" in now and str(exe) in now and f"[tools] {name}" in now
        assert waits in now
        exe.write_bytes(b"")
        eventually(lambda: f"Can't find {name}" not in c.get("/").text)


def test_makemkv_is_checked_again_on_its_own_until_it_is_fixed(tmp_path):
    h = make_harness(tmp_path)
    h.makemkv_check["key"] = ""
    with TestClient(create_app(h.services)) as c:
        eventually(lambda: "Rips are paused" in c.get("/").text)
        h.makemkv_check["key"] = "T-fixed"  # registered in MakeMKV; nobody presses a button
        eventually(lambda: "Rips are paused" not in c.get("/").text)


def test_check_again_rechecks_makemkv(tmp_path):
    h = make_harness(tmp_path)
    h.makemkv_check["key"] = ""
    with TestClient(create_app(h.services)) as c:
        eventually(lambda: "isn't registered" in html.unescape(c.get("/makemkv").text))
        h.makemkv_check["key"] = "T-fixed"
        r = c.post("/makemkv/check", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/makemkv"
        page = html.unescape(c.get("/makemkv").text)
        assert "MakeMKV v2.0.0 is ready" in page
        assert "paused" not in c.get("/").text


def test_video_rip_is_refused_until_makemkv_passes_its_checks(tmp_path):
    from ama.drive import DiscType

    h = make_harness(tmp_path)
    h.makemkv_check["key"] = ""
    h.makemkv.release()
    with TestClient(create_app(h.services)) as c:
        eventually(lambda: "isn't registered" in html.unescape(c.get("/makemkv").text))
        h.drive.insert(DiscType.BD, "MATRIX_BD")
        eventually(lambda: h.drive.ejected == 1)
        assert h.makemkv.calls == []  # makemkvcon never ran
        now = html.unescape(c.get("/").text)
        assert "MakeMKV isn't registered." in now and "MATRIX_BD" in now
        page = html.unescape(c.get("/jobs/1").text)
        assert "MakeMKV isn't registered." in page and 'href="/makemkv"' in page
        assert "This isn't a problem with the Disc" in page

        # Fixed and re-checked: the next insertion rips.
        h.makemkv_check["key"] = "T-fixed"
        c.post("/makemkv/check")
        h.drive.insert(DiscType.BD, "MATRIX_BD")
        eventually(lambda: h.drive.ejected == 2)
        assert h.makemkv.calls


def test_cd_waits_for_cyanrip_then_rips_and_video_is_not_blocked(tmp_path):
    import hashlib

    from ama.drive import DiscType
    from ama.tools import Member, Pin

    exe = b"pretend cyanrip"
    sha = hashlib.sha256(exe).hexdigest()
    pin = Pin("cyanrip", "1", "https://example/cyanrip.exe", sha, (Member("cyanrip", None, sha),))

    class OfflineUntilReleased(FakeFetch):
        online = False

        def __call__(self, url, dest, progress):
            if not self.online:
                self.calls.append(url)
                raise OSError("offline")
            super().__call__(url, dest, progress)

    fetch = OfflineUntilReleased({pin.url: exe})
    h = make_harness(tmp_path, fetch=fetch, pins=(pin,))
    with TestClient(create_app(h.services)) as c:
        eventually(lambda: "Couldn't download cyanrip" in html.unescape(c.get("/").text))
        h.drive.insert(DiscType.CD, "Audio CD")
        time.sleep(0.3)  # many CD Rip polls
        assert h.cyanrip.calls == [] and h.drive.ejected == 0  # waiting, not failed
        assert "CD Rips wait" in html.unescape(c.get("/").text)

        h.drive.eject()
        h.makemkv.release()
        h.drive.insert(DiscType.BD, "MATRIX_BD")  # makemkvcon is ready: video isn't blocked
        eventually(lambda: h.makemkv.calls)
        eventually(lambda: h.drive.ejected == 2)

        h.drive.insert(DiscType.CD, "Audio CD")
        fetch.online = True  # the retry fetches cyanrip, and the waiting CD rips
        eventually(lambda: h.cyanrip.calls)
