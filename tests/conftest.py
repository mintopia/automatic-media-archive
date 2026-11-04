from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass

import pytest
import uvicorn
from fastapi.testclient import TestClient

from ama.app import Services, build_services, create_app
from ama.config import (
    Config,
    CqConfig,
    DriveConfig,
    EncodeConfig,
    NasConfig,
    PathsConfig,
    ToolsConfig,
    WebConfig,
)
from ama.events import EventBus
from ama.proc import ProcResult
from ama.tools import Tools
from tests.fakes import FakeDrive, FakeFetch, FakeRunner

UNC = r"\\nas\media"
MAKEMKV_OK = ('MSG:1005,0,1,"MakeMKV v2.0.0 win(x64-release) started","%1 started",'
              '"MakeMKV v2.0.0 win(x64-release)"\n')


def make_config(tmp_path, password: str = "") -> Config:
    return Config(
        web=WebConfig(password=password),
        drive=DriveConfig(poll_seconds=0.01),
        nas=NasConfig(unc=UNC, retry_seconds=0.05),
        paths=PathsConfig(scratch=tmp_path / "scratch", state_db=tmp_path / "ama.sqlite3",
                          log_file=tmp_path / "ama.log"),
        encode=EncodeConfig(cq=CqConfig(dvd=20, bd=22, uhd=22)),
    )


@dataclass
class Harness:
    """The app wired to fakes: a controllable drive and a controllable NAS share."""

    services: Services
    drive: FakeDrive
    share: dict  # {"reachable": bool}
    runner: FakeRunner
    makemkv: dict  # {"key": str, "output": str}: what the fake MakeMKV says on the next check


def make_harness(tmp_path, password: str = "", nas_reachable: bool = True,
                 fetch: FakeFetch | None = None) -> Harness:
    """Tools default to ready: config overrides for ffmpeg/ffprobe/cyanrip, a registered
    MakeMKV. Pass `fetch` to provision the managed tools from fake downloads instead."""
    cfg = make_config(tmp_path, password)
    drive = FakeDrive()
    share = {"reachable": nas_reachable}
    runner = FakeRunner(lambda a: ProcResult(2, "System error 53 has occurred.\n\n"
                                                "The network path was not found."))
    makemkv = {"key": "T-test", "output": MAKEMKV_OK}
    exe = tmp_path / "MakeMKV" / "makemkvcon64.exe"
    exe.parent.mkdir(exist_ok=True)
    exe.write_bytes(b"")
    fakes = {} if fetch else {n: str(tmp_path / f"{n}.exe") for n in ("ffmpeg", "ffprobe", "cyanrip")}

    def make_tools(bus: EventBus) -> Tools:
        return Tools(ToolsConfig(dir=str(tmp_path / "tools"), **fakes), bus,
                     runner=FakeRunner(lambda a: ProcResult(0, makemkv["output"])),
                     fetch=fetch or FakeFetch({}), read_key=lambda: makemkv["key"],
                     makemkv_candidates=[exe], retry_seconds=0.05)

    services = build_services(cfg, probe=drive, runner=runner,
                              nas_exists=lambda p: share["reachable"], make_tools=make_tools)
    return Harness(services, drive, share, runner, makemkv)


def eventually(check: Callable[[], bool], timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while not check():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        time.sleep(0.02)


@pytest.fixture
def harness(tmp_path) -> Harness:
    return make_harness(tmp_path)


@pytest.fixture
def client(harness) -> Iterator[TestClient]:
    with TestClient(create_app(harness.services)) as c:
        yield c


@pytest.fixture
def live_server(harness) -> Iterator[str]:
    """The app served by real uvicorn on a free port (for streaming SSE)."""
    server = uvicorn.Server(uvicorn.Config(create_app(harness.services), host="127.0.0.1",
                                           port=0, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    eventually(lambda: server.started)
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    t.join(5)
