"""Setup's drive and MakeMKV step, and AMA's tools downloading in the background (#72)."""

from __future__ import annotations

import asyncio
import hashlib
import html
import re
import threading
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from ama.config import ToolsConfig, load_config
from ama.events import EventBus
from ama.proc import ProcResult
from ama.setup import Setup, create_setup_app, run_setup
from ama.setup.machine import Machine
from ama.tools import Member, Pin, Tools
from ama.web.auth import CONTROL_HEADER
from tests.conftest import MAKEMKV_OK, eventually
from tests.fakes import FakeRunner

FFMPEG, CYANRIP = b"pretend ffmpeg.exe", b"pretend cyanrip.exe"


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


PINS = (
    Pin(key="ffmpeg", version="9", url="https://example/ffmpeg.exe", sha256=_sha(FFMPEG),
        members=(Member("ffmpeg", None, _sha(FFMPEG)),)),
    Pin(key="cyanrip", version="1", url="https://example/cyanrip.exe", sha256=_sha(CYANRIP),
        members=(Member("cyanrip", None, _sha(CYANRIP)),)),
)
FILES = {p.url: data for p, data in zip(PINS, (FFMPEG, CYANRIP), strict=True)}


class GatedFetch:
    """A download that sends half, then waits for `release` (or fails if told to)."""

    def __init__(self) -> None:
        self.gate = threading.Event()
        self.halfway = threading.Event()
        self.calls: list[str] = []
        self.fail: str | None = None

    def release(self) -> None:
        self.gate.set()

    def __call__(self, url: str, dest: Path, progress: Callable[[int, int | None], None]) -> None:
        self.calls.append(url)
        data = FILES[url]
        dest.write_bytes(data[:4])
        progress(4, len(data))
        self.halfway.set()
        assert self.gate.wait(10)
        if self.fail:
            raise OSError(self.fail)
        dest.write_bytes(data)
        progress(len(data), len(data))


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


@pytest.fixture
def makemkv(tmp_path) -> dict:
    """What the fake MakeMKV is like: installed (exe), what it prints, its key."""
    exe = tmp_path / "MakeMKV" / "makemkvcon64.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"")
    return {"exe": exe, "output": MAKEMKV_OK, "key": "T-key"}


@pytest.fixture
def fetch() -> GatedFetch:
    return GatedFetch()


@pytest.fixture
def drives() -> list[str]:
    return ["D:"]


@pytest.fixture
def machine(tmp_path, makemkv, fetch, drives) -> Machine:
    tools = Tools(ToolsConfig(dir=str(tmp_path / "tools")), EventBus(),
                  runner=FakeRunner(lambda a: ProcResult(0, makemkv["output"])), fetch=fetch,
                  read_key=lambda: makemkv["key"], pins=PINS,
                  makemkv_candidates=[makemkv["exe"]])
    return Machine(tools, drives=lambda: tuple(drives))


@pytest.fixture
def setup(tmp_path, home, machine) -> Setup:
    return Setup(tmp_path / "AMA" / "ama.toml", machine=machine)


@pytest.fixture
def client(setup) -> TestClient:
    return TestClient(create_setup_app(setup))


def _title(page: str) -> str:
    return page.split("<h1>", 1)[1].split("</h1>", 1)[0]


def test_the_drive_step_comes_between_welcome_and_where_things_go(client):
    r = client.post("/setup/welcome")
    assert r.request.url.path == "/setup/drive" and _title(r.text) == "Drive and MakeMKV"
    r = client.post("/setup/drive", data={"drive": "D:"})
    assert r.request.url.path == "/setup/where"


def _form(page: str) -> dict[str, str]:
    """What the page's form posts as it stands."""
    form = dict(re.findall(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', page))
    if chosen := re.search(r'<select[^>]*name="([^"]+)"[\s\S]*?<option value="([^"]*)" selected',
                           page):
        form[chosen[1]] = chosen[2]
    return form


def _continue(client: TestClient, *slugs: str) -> None:
    for slug in slugs:
        r = client.post(f"/setup/{slug}", data=_form(client.get(f"/setup/{slug}").text))
        assert r.status_code == 200, r.text


def _finish(client: TestClient) -> None:
    _continue(client, "welcome", "drive", "where")
    r = client.post("/setup/ready")
    assert "Starting AMA" in r.text, r.text


@pytest.mark.parametrize("drives", [["E:", "F:"]])
def test_the_auto_detected_drive_is_offered_and_another_can_be_chosen(client, setup, drives):
    page = client.get("/setup/drive").text
    assert '<option value="E:" selected>' in page and '<option value="F:">' in page
    client.post("/setup/drive", data={"drive": "F:"})
    _continue(client, "where")
    client.post("/setup/ready")
    assert load_config(setup.config).drive.letter == "F:"


def test_confirming_the_detected_drive_writes_it(client, setup):
    _finish(client)
    assert load_config(setup.config).drive.letter == "D:"


@pytest.mark.parametrize("drives", [[]])
def test_with_no_drive_found_setup_carries_on_and_ama_finds_one_later(client, setup, drives):
    assert "No optical drive found" in client.get("/setup/drive").text
    _finish(client)
    assert load_config(setup.config).drive.letter == ""


def _makemkv_says(client: TestClient, machine: Machine) -> str:
    asyncio.run(machine.tools.check_makemkv())
    page = client.get("/setup/drive").text
    return html.unescape(page.split("<h2>MakeMKV</h2>", 1)[1].split("</form>", 1)[0])


def test_makemkv_installed_and_registered_is_shown_as_ready(client, machine):
    assert "MakeMKV v2.0.0 is installed and registered" in _makemkv_says(client, machine)


def test_makemkv_found_but_not_registered_says_so(client, machine, makemkv):
    makemkv["key"] = ""
    said = _makemkv_says(client, machine)
    assert "isn't registered" in said and "Help → Register" in said


def test_makemkv_missing_links_to_its_installer_and_setup_carries_on(client, machine, makemkv,
                                                                     setup):
    makemkv["exe"].unlink()
    said = _makemkv_says(client, machine)
    assert "Can't find MakeMKV" in said and "CDs still work" in said
    assert 'href="https://www.makemkv.com/download/"' in said
    _finish(client)
    assert setup.config.exists()


def test_the_drive_shows_makemkvs_name_for_it(client, machine):
    machine.tools.drive_names["D:"] = "HL-DT-ST BD-RE WH16NS40"
    assert '<option value="D:" selected>D: · HL-DT-ST BD-RE WH16NS40</option>' in client.get(
        "/setup/drive").text


def test_a_drive_that_isnt_a_letter_is_refused(client):
    r = client.post("/setup/drive", data={"drive": "nonsense"})
    assert r.status_code == 422 and "Choose a drive" in r.text


def _downloads(page: str) -> str:
    return html.unescape(page.split('id="setup-downloads"', 1)[1].split("</section>", 1)[0])


def test_the_tools_start_downloading_as_soon_as_setup_opens(setup, machine, fetch):
    opened: list[str] = []
    done: list[bool] = []
    t = threading.Thread(target=lambda: done.append(run_setup(
        setup.config, port=0, open_url=opened.append, control_token="tok", machine=machine)))
    t.start()
    eventually(lambda: opened)
    assert fetch.halfway.wait(10)  # nobody has looked at a page yet
    assert fetch.calls == ["https://example/ffmpeg.exe"]
    fetch.release()
    httpx.post(opened[0] + "control/quit", headers={CONTROL_HEADER: "tok"})
    t.join(10)
    assert done == [False]


def test_ready_shows_the_downloads_progress_and_finish_waits_for_them(client, setup, machine,
                                                                     fetch):
    machine.start()
    assert fetch.halfway.wait(10)
    _continue(client, "welcome", "drive", "where")
    page = client.get("/setup/ready").text
    shown = _downloads(page)
    assert "ffmpeg 9" in shown and 'role="meter"' in shown and "Waiting" in shown  # cyanrip
    assert 'hx-get="/setup-downloads"' in page  # it keeps itself up to date
    r = client.post("/setup/ready")
    assert r.status_code == 422 and "still downloading" in r.text
    assert not setup.config.exists()
    fetch.release()
    eventually(lambda: not machine.busy)
    page = client.get("/setup-downloads").text
    assert "hx-get" not in page and _downloads(page).count("Downloaded") == 2
    assert "Starting AMA" in client.post("/setup/ready").text


def test_a_failed_download_is_shown_with_a_retry_and_doesnt_hold_setup_up(client, setup,
                                                                          machine, fetch):
    fetch.fail = "the network is down"
    fetch.release()
    machine.start()
    eventually(lambda: not machine.busy)
    _continue(client, "welcome", "drive", "where")
    shown = _downloads(client.get("/setup/ready").text)
    assert "Couldn't download ffmpeg 9" in shown and "the network is down" in shown
    assert 'formaction="/setup-downloads/retry"' in shown
    fetch.fail = None
    r = client.post("/setup-downloads/retry")
    assert r.request.url.path == "/setup/ready"
    eventually(lambda: not machine.busy)
    assert "Couldn't download" not in _downloads(client.get("/setup/ready").text)
    assert machine.tools.path("ffmpeg").read_bytes() == FFMPEG
    _finish(client)
    assert setup.config.exists()


def test_a_failed_download_doesnt_stop_setup_finishing(client, setup, machine, fetch):
    fetch.fail = "the network is down"
    fetch.release()
    machine.start()
    eventually(lambda: not machine.busy)
    _finish(client)  # AMA keeps trying once it's running
    assert setup.config.exists()
