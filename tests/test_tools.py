"""Portable tool provisioning and the one resolver (ADR 0006), against fake downloads."""

import asyncio
import hashlib
import io
import zipfile
from pathlib import Path

import pytest

from ama.config import ToolsConfig
from ama.events import EventBus
from ama.tools import Member, Pin, ToolFailed, ToolReady, Tools, ToolUnavailable
from tests.fakes import FakeFetch, FakeRunner

FFMPEG = b"pretend ffmpeg.exe"
FFPROBE = b"pretend ffprobe.exe"
CYANRIP = b"pretend cyanrip.exe"


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


FFMPEG_ZIP = _zip({"ffmpeg-9/bin/ffmpeg.exe": FFMPEG, "ffmpeg-9/bin/ffprobe.exe": FFPROBE,
                   "ffmpeg-9/doc/readme.txt": b"docs"})
PINS = (
    Pin(key="ffmpeg", version="9", url="https://example/ffmpeg.zip", sha256=_sha(FFMPEG_ZIP),
        members=(Member("ffmpeg", "ffmpeg-9/bin/ffmpeg.exe", _sha(FFMPEG)),
                 Member("ffprobe", "ffmpeg-9/bin/ffprobe.exe", _sha(FFPROBE)))),
    Pin(key="cyanrip", version="1", url="https://example/cyanrip.exe", sha256=_sha(CYANRIP),
        members=(Member("cyanrip", None, _sha(CYANRIP)),)),
)
GOOD = {"https://example/ffmpeg.zip": FFMPEG_ZIP, "https://example/cyanrip.exe": CYANRIP}


def make_tools(tmp_path, fetch, **overrides) -> Tools:
    cfg = ToolsConfig(dir=str(tmp_path / "tools"), **overrides)
    return Tools(cfg, EventBus(), runner=FakeRunner(), fetch=fetch, read_key=lambda: "",
                 pins=PINS, makemkv_candidates=())


def test_fresh_start_downloads_verifies_and_unpacks_each_tool(tmp_path):
    fetch = FakeFetch(GOOD)
    tools = make_tools(tmp_path, fetch)
    asyncio.run(tools.provision())
    assert tools.path("ffmpeg").read_bytes() == FFMPEG
    assert tools.path("ffprobe").read_bytes() == FFPROBE
    assert tools.path("cyanrip").read_bytes() == CYANRIP
    assert tools.path("ffmpeg").is_relative_to(tmp_path / "tools")
    assert sorted(fetch.calls) == sorted(GOOD)


def test_second_start_downloads_nothing(tmp_path):
    asyncio.run(make_tools(tmp_path, FakeFetch(GOOD)).provision())
    fetch = FakeFetch(GOOD)
    tools = make_tools(tmp_path, fetch)
    asyncio.run(tools.provision())
    assert fetch.calls == []
    assert tools.path("cyanrip").read_bytes() == CYANRIP


def test_a_tool_is_unavailable_until_provisioned(tmp_path):
    tools = make_tools(tmp_path, FakeFetch(GOOD))
    with pytest.raises(ToolUnavailable) as e:
        tools.path("ffmpeg")
    assert e.value.name == "ffmpeg"


def test_corrupt_download_is_rejected_by_hash_and_refetched(tmp_path):
    fetch = FakeFetch(GOOD)
    fetch.serve_once("https://example/cyanrip.exe", b"truncated")
    tools = make_tools(tmp_path, fetch)
    asyncio.run(tools.provision())
    status = tools.status("cyanrip")
    assert isinstance(status, ToolFailed) and "SHA-256" in status.detail
    with pytest.raises(ToolUnavailable):
        tools.path("cyanrip")
    assert tools.path("ffmpeg").read_bytes() == FFMPEG  # only the work that needs cyanrip waits

    asyncio.run(tools.provision())  # the retry
    assert tools.path("cyanrip").read_bytes() == CYANRIP
    assert fetch.calls.count("https://example/cyanrip.exe") == 2


def test_corrupted_installed_tool_is_refetched_on_next_start(tmp_path):
    first = make_tools(tmp_path, FakeFetch(GOOD))
    asyncio.run(first.provision())
    first.path("ffprobe").write_bytes(b"damaged")
    fetch = FakeFetch(GOOD)
    tools = make_tools(tmp_path, fetch)
    asyncio.run(tools.provision())
    assert fetch.calls == ["https://example/ffmpeg.zip"]
    assert tools.path("ffprobe").read_bytes() == FFPROBE


def test_failed_download_is_reported_and_leaves_no_partial_tool(tmp_path):
    fetch = FakeFetch(GOOD)
    fetch.fail_once("https://example/ffmpeg.zip", OSError("connection reset"))
    tools = make_tools(tmp_path, fetch)
    asyncio.run(tools.provision())
    status = tools.status("ffmpeg")
    assert isinstance(status, ToolFailed) and "connection reset" in status.detail
    assert not list((tmp_path / "tools").rglob("ffmpeg.exe"))


def test_config_override_is_used_as_is_with_no_download(tmp_path):
    fetch = FakeFetch(GOOD)
    tools = make_tools(tmp_path, fetch, cyanrip=r"C:\custom\cyanrip.exe")
    assert tools.path("cyanrip") == Path(r"C:\custom\cyanrip.exe")
    asyncio.run(tools.provision())
    assert fetch.calls == ["https://example/ffmpeg.zip"]
    assert isinstance(tools.status("cyanrip"), ToolReady)


def test_overriding_every_member_of_an_archive_skips_its_download(tmp_path):
    fetch = FakeFetch(GOOD)
    tools = make_tools(tmp_path, fetch, ffmpeg=r"C:\f\ffmpeg.exe", ffprobe=r"C:\f\ffprobe.exe")
    asyncio.run(tools.provision())
    assert fetch.calls == ["https://example/cyanrip.exe"]


def test_download_progress_is_published(tmp_path):
    fetch = FakeFetch(GOOD)
    tools = make_tools(tmp_path, fetch)
    seen = []

    async def go():
        with tools.bus.subscribe() as q:
            await tools.provision()
            while not q.empty():
                seen.append(q.get_nowait())

    asyncio.run(go())
    assert "tools" in seen


def test_run_retries_failed_downloads_until_ready(tmp_path):
    fetch = FakeFetch(GOOD)
    fetch.fail_once("https://example/ffmpeg.zip", OSError("offline"))
    tools = make_tools(tmp_path, fetch)
    tools.retry_seconds = 0.01
    asyncio.run(asyncio.wait_for(tools.run(), 5))
    assert tools.path("ffmpeg").read_bytes() == FFMPEG


def test_unknown_tool_name_is_a_programming_error(tmp_path):
    with pytest.raises(KeyError):
        make_tools(tmp_path, FakeFetch(GOOD)).path("handbrake")


def test_real_pins_are_complete():
    from ama.tools import PINS as REAL

    names = {m.name for p in REAL for m in p.members}
    assert names == {"ffmpeg", "ffprobe", "cyanrip"}
    for p in REAL:
        assert p.url.startswith("https://github.com/")
        assert len(p.sha256) == 64 and all(len(m.sha256) == 64 for m in p.members)
