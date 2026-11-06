from __future__ import annotations

import asyncio
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
    DiscordConfig,
    DriveConfig,
    EncodeConfig,
    NtfyConfig,
    PathsConfig,
    PlexConfig,
    TmdbConfig,
    ToolsConfig,
    WebConfig,
)
from ama.config import Library, LibraryKind, load_config
from ama.events import EventBus
from ama.proc import ProcResult
from ama.settings import upgrade
from ama.tools import Tools
from tests.fakes import (
    FakeCyanrip,
    FakeDisk,
    FakeDrive,
    FakeFetch,
    FakeFfmpeg,
    FakeMakemkv,
    FakeRunner,
    FakeTools,
    FakeWeb,
)

MAKEMKV_OK = ('MSG:1005,0,1,"MakeMKV v2.0.0 win(x64-release) started","%1 started",'
              '"MakeMKV v2.0.0 win(x64-release)"\n')


def make_config(tmp_path, password: str = "", discord: str = "", ntfy_topic: str = "",
                tmdb_key: str = "tmdb-key") -> Config:
    return Config(
        discord=DiscordConfig(webhook_url=discord),
        ntfy=NtfyConfig(topic=ntfy_topic),
        web=WebConfig(password=password),
        drive=DriveConfig(poll_seconds=0.01),
        plex=PlexConfig(url="http://plex:32400", token="plex-token",
                        libraries_path="/volume1/media"),
        libraries=tuple(Library(name=k.folder, kind=k, path=str(tmp_path / "libraries" / k.folder),
                                default=True) for k in LibraryKind),
        paths=PathsConfig(scratch=tmp_path / "scratch", state_db=tmp_path / "ama.sqlite3",
                          log_file=tmp_path / "ama.log"),
        encode=EncodeConfig(cq=CqConfig(dvd=20, bd=22, uhd=24)),
        tmdb=TmdbConfig(api_key=tmdb_key),
    )


@dataclass
class Harness:
    """The app wired to fakes: a controllable drive, Library folders and makemkvcon."""

    services: Services
    drive: FakeDrive
    runner: FakeRunner
    makemkv: FakeMakemkv  # the makemkvcon that Video Rips run
    cyanrip: FakeCyanrip
    makemkv_check: dict  # {"key", "output"}: what the MakeMKV preflight sees next
    web: FakeWeb  # MusicBrainz, Cover Art Archive, Plex, TMDB
    libraries_root: Path  # each default Library is a folder in here
    ffmpeg: FakeFfmpeg  # ffprobe + the Encode
    disk: FakeDisk  # the scratch volume's size and use

    def drop_library(self, kind: LibraryKind) -> Path:
        """Make the kind's default Library folder unreachable, like a dropped mapped drive:
        a file stands where the folder was. Its path."""
        path = Path(next(lib.path for lib in self.services.archive.libraries
                         if lib.kind == kind and lib.default))
        if path.is_dir():
            path.rename(path.with_name(path.name + ".away"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
        return path

    def restore_library(self, kind: LibraryKind) -> None:
        path = Path(next(lib.path for lib in self.services.archive.libraries
                         if lib.kind == kind and lib.default))
        path.unlink()
        away = path.with_name(path.name + ".away")
        if away.is_dir():
            away.rename(path)

    def films_pattern(self, pattern: str) -> None:
        """Give every Films Library `pattern`, as a Settings save applies it live."""
        cfg = self.services.config
        self.services.apply_live(Config.model_validate(cfg.model_dump() | {"libraries": [
            lib.model_dump() | ({"pattern": pattern} if lib.kind == LibraryKind.FILMS else {})
            for lib in cfg.libraries]}))

    def tv_pattern(self, pattern: str) -> None:
        """Give every TV Library `pattern`, as a Settings save applies it live."""
        cfg = self.services.config
        self.services.apply_live(Config.model_validate(cfg.model_dump() | {"libraries": [
            lib.model_dump() | ({"pattern": pattern} if lib.kind == LibraryKind.TV else {})
            for lib in cfg.libraries]}))


def write_config(tmp_path, extra: str = "") -> Path:
    """An ama.toml like `make_config`'s, with comments, for the Settings tests."""
    p = tmp_path / "ama.toml"
    root = tmp_path / "libraries"
    libraries = "" if "[[libraries]]" in extra else "".join(
        f"\n[[libraries]]\nname = \"{k.folder}\"\nkind = \"{k.value}\"\n"
        f"path = '{root / k.folder}'\ndefault = true\n" for k in LibraryKind)
    p.write_text(f"""# AMA test config
[web]
# Who can open AMA.
host = "0.0.0.0"
port = 8080
password = ""

[drive]
letter = ""
poll_seconds = 0.01

[cd]
offset = 667
retries = 10

[paths]
scratch = 'scratch'
state_db = "ama.sqlite3"
log_file = "ama.log"

[tmdb]
api_key = "tmdb-key"

[plex]
url = "http://plex:32400"
token = "plex-token"
libraries_path = "/volume1/media"

[encode.cq]
# CQ per Disc Type.
dvd = 20
bd = 22
uhd = 24
{extra}{libraries}""", encoding="utf-8")
    return p


def make_harness(tmp_path, password: str = "",
                 fetch: FakeFetch | None = None, pins: tuple | None = None,
                 discord: str = "", ntfy_topic: str = "",
                 config_file: Path | None = None, tmdb_key: str = "tmdb-key") -> Harness:
    """Tools default to ready: config overrides for ffmpeg/ffprobe/cyanrip, a registered
    MakeMKV. Pass `fetch` to provision the managed tools from fake downloads instead.
    `config_file` (from `write_config`) runs from a real ama.toml, as Settings edits it."""
    if config_file:
        upgrade(config_file)
    cfg = load_config(config_file) if config_file else make_config(
        tmp_path, password, discord, ntfy_topic, tmdb_key)
    drive = FakeDrive()
    runner = FakeRunner(lambda a: ProcResult(1, ""))
    makemkv = FakeMakemkv(drive)
    cyanrip = FakeCyanrip(drive)
    web = FakeWeb()
    makemkv_check = {"key": "T-test", "output": MAKEMKV_OK}
    exe = tmp_path / "MakeMKV" / "makemkvcon64.exe"
    exe.parent.mkdir(exist_ok=True)
    exe.write_bytes(b"")
    fakes = {} if fetch else {n: str(tmp_path / f"{n}.exe") for n in ("ffmpeg", "ffprobe", "cyanrip")}
    for path in fakes.values():  # an override is only ready while its file is there
        Path(path).write_bytes(b"")

    def make_tools(bus: EventBus) -> Tools:
        return Tools(ToolsConfig(dir=str(tmp_path / "tools"), **fakes), bus,
                     runner=FakeRunner(lambda a: ProcResult(0, makemkv_check["output"])),
                     fetch=fetch or FakeFetch({}), read_key=lambda: makemkv_check["key"],
                     makemkv_candidates=[exe], retry_seconds=0.05,
                     **({} if pins is None else {"pins": pins}))

    ffmpeg = FakeFfmpeg()
    disk = FakeDisk()
    services = build_services(cfg, probe=drive, runner=runner,
                              streamer=FakeTools(makemkv, cyanrip, ffmpeg),
                              make_tools=make_tools,
                              http=httpx.Client(transport=web.transport()),
                              disc_root=lambda: drive.root, disk_usage=disk,
                              config_path=config_file)
    # Preflight now, so a Disc inserted right after startup never races the first check.
    asyncio.run(services.tools.check_makemkv())
    for archiver in (services.cd_archive, services.movie_archive, services.tv_archive):
        archiver.backoff.retry_seconds = 0.05
    services.musicbrainz.min_interval = 0  # no MusicBrainz rate limit against the fake
    return Harness(services, drive, runner, makemkv, cyanrip, makemkv_check, web,
                   tmp_path / "libraries", ffmpeg, disk)


def eventually(check: Callable[[], bool], timeout: float = 15.0) -> None:
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
