from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx
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
    PlexConfig,
    WebConfig,
)
from ama.proc import ProcResult
from tests.fakes import FakeCyanrip, FakeDrive, FakeMakemkv, FakeRunner, FakeTools, FakeWeb


def make_config(tmp_path, password: str = "") -> Config:
    return Config(
        web=WebConfig(password=password),
        drive=DriveConfig(poll_seconds=0.01),
        # The "NAS share" is a local folder; reachability is faked by `nas_exists`.
        nas=NasConfig(unc=str(tmp_path / "nas"), retry_seconds=0.05),
        plex=PlexConfig(url="http://plex:32400", token="plex-token", nas_path="/volume1/media"),
        paths=PathsConfig(scratch=tmp_path / "scratch", state_db=tmp_path / "ama.sqlite3",
                          log_file=tmp_path / "ama.log"),
        encode=EncodeConfig(cq=CqConfig(dvd=20, bd=22, uhd=22)),
    )


@dataclass
class Harness:
    """The app wired to fakes: a controllable drive, NAS share and makemkvcon."""

    services: Services
    drive: FakeDrive
    share: dict  # {"reachable": bool}
    runner: FakeRunner
    makemkv: FakeMakemkv
    cyanrip: FakeCyanrip
    web: FakeWeb  # MusicBrainz, Cover Art Archive, Plex
    nas_root: Path


def make_harness(tmp_path, password: str = "", nas_reachable: bool = True) -> Harness:
    cfg = make_config(tmp_path, password)
    drive = FakeDrive()
    share = {"reachable": nas_reachable}
    runner = FakeRunner(lambda a: ProcResult(2, "System error 53 has occurred.\n\n"
                                                "The network path was not found."))
    makemkv = FakeMakemkv(drive)
    cyanrip = FakeCyanrip(drive)
    web = FakeWeb()
    services = build_services(cfg, probe=drive, runner=runner,
                              nas_exists=lambda p: share["reachable"],
                              streamer=FakeTools(makemkv, cyanrip),
                              http=httpx.Client(transport=web.transport()))
    services.cd_archive.retry_seconds = 0.05
    services.musicbrainz.min_interval = 0  # no MusicBrainz rate limit against the fake
    return Harness(services, drive, share, runner, makemkv, cyanrip, web, Path(cfg.nas.unc))


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
