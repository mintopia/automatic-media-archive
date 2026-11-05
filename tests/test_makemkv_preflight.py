"""MakeMKV preflight: present, runs, registered (ADR 0006). Outputs are real captures."""

import asyncio
from pathlib import Path

import pytest

from ama.config import ToolsConfig
from ama.events import EventBus
from ama.proc import ProcResult
from ama.tools import (
    MakemkvBroken,
    MakemkvKeyRejected,
    MakemkvMissing,
    MakemkvTooOld,
    MakemkvUnregistered,
    ToolReady,
    Tools,
    ToolUnavailable,
)
from tests.fakes import FakeRunner

DATA = Path(__file__).parent / "data"
V2 = (DATA / "makemkv-unregistered-v2.0.0.txt").read_text(encoding="utf-8")
TOO_OLD = (DATA / "makemkv-licence-too-old.txt").read_text(encoding="utf-8")
EXPIRED = ('MSG:1005,0,1,"MakeMKV v1.18.2 win(x64-release) started","%1 started","MakeMKV v1.18.2"\n'
           'MSG:5055,516,0,"Evaluation period has expired, shareware functionality unavailable.",'
           '"Evaluation period has expired, shareware functionality unavailable."\n')


@pytest.fixture
def exe(tmp_path) -> Path:
    p = tmp_path / "MakeMKV" / "makemkvcon64.exe"
    p.parent.mkdir()
    p.write_bytes(b"")
    return p


def check(exe: Path | None, output: str = V2, key: str = "T-key", code: int = 0,
          override: str = "", runner=None):
    runner = runner or FakeRunner(lambda a: ProcResult(code, output))
    tools = Tools(ToolsConfig(makemkvcon=override), EventBus(), runner=runner,
                  read_key=lambda: key, pins=(),
                  makemkv_candidates=[Path("Z:/nowhere/makemkvcon64.exe")] + ([exe] if exe else []))
    status = asyncio.run(tools.check_makemkv())
    return tools, status, runner


def test_installed_registered_makemkv_is_ready(exe):
    tools, status, runner = check(exe)
    assert status == ToolReady(exe, "installed", "2.0.0")
    assert tools.path("makemkvcon") == exe
    assert runner.calls == [[str(exe), "-r", "--cache=1", "info", "disc:9999"]]


def test_missing_makemkv_says_where_it_looked(tmp_path):
    tools, status, _ = check(None)
    assert isinstance(status, MakemkvMissing)
    assert any("nowhere" in s for s in status.searched)
    with pytest.raises(ToolUnavailable):
        tools.path("makemkvcon")


def test_too_old_build_is_msg_5021(exe):
    tools, status, _ = check(exe, TOO_OLD, code=127)
    assert status == MakemkvTooOld("1.18.2")
    with pytest.raises(ToolUnavailable):
        tools.path("makemkvcon")


def test_running_but_unregistered(exe):
    _, status, _ = check(exe, key="")
    assert status == MakemkvUnregistered("2.0.0")


def test_expired_evaluation_or_bad_key(exe):
    _, status, _ = check(exe, EXPIRED)
    assert status == MakemkvKeyRejected("1.18.2")


def test_program_that_doesnt_start_is_broken(exe):
    def boom(args):
        raise OSError("[WinError 216] This version of %1 is not compatible")

    _, status, _ = check(exe, runner=FakeRunner(boom))
    assert isinstance(status, MakemkvBroken) and "WinError 216" in status.detail


def test_output_without_makemkv_banner_is_broken(exe):
    _, status, _ = check(exe, "Access is denied.\n", code=1)
    assert isinstance(status, MakemkvBroken) and "Access is denied." in status.detail


def test_config_override_is_checked_too(exe, tmp_path):
    custom = tmp_path / "elsewhere.exe"
    custom.write_bytes(b"")
    _, status, runner = check(None, override=str(custom))
    assert status == ToolReady(custom, "config", "2.0.0")
    assert runner.calls[0][0] == str(custom)


def test_rechecking_after_the_user_fixes_it(exe):
    key = {"v": ""}
    tools = Tools(ToolsConfig(), EventBus(), runner=FakeRunner(lambda a: ProcResult(0, V2)),
                  read_key=lambda: key["v"], pins=(), makemkv_candidates=[exe])
    assert isinstance(asyncio.run(tools.check_makemkv()), MakemkvUnregistered)
    key["v"] = "T-abc"
    asyncio.run(tools.check_makemkv())
    assert tools.path("makemkvcon") == exe


def test_makemkv_that_hangs_is_reported_not_waited_on_forever(exe):
    import subprocess

    def hang(args):
        raise subprocess.TimeoutExpired(args, 120)

    _, status, _ = check(exe, runner=FakeRunner(hang))
    assert isinstance(status, MakemkvBroken) and "didn't finish" in status.detail


def test_provisioning_does_not_wait_for_the_makemkv_check(exe, tmp_path):
    import threading

    gate = threading.Event()

    def slow(args):
        gate.wait(5)
        return ProcResult(0, V2)

    overrides = {n: tmp_path / f"{n}.exe" for n in ("ffmpeg", "ffprobe", "cyanrip")}
    for path in overrides.values():
        path.write_bytes(b"")
    tools = Tools(ToolsConfig(dir=str(tmp_path / "t"), **{n: str(p) for n, p in overrides.items()}),
                  EventBus(), runner=FakeRunner(slow), read_key=lambda: "k", pins=(),
                  makemkv_candidates=[exe])

    async def go():
        task = asyncio.create_task(tools.run())
        await asyncio.sleep(0.2)
        assert not task.done()  # still checking MakeMKV...
        provisioned = tools.status("ffmpeg")  # ...but provisioning already ran
        gate.set()
        await task
        return provisioned

    assert isinstance(asyncio.run(go()), ToolReady)
