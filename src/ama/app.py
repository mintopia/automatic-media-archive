"""Wiring: build the long-lived services, and the FastAPI app that serves them.

`build_services` is the one place real OS/process adapters are chosen; tests
pass fakes for `probe`, `runner`, `streamer`, `tool`, `make_tools`, `nas_exists`
and `http` (an httpx client, e.g. over a MockTransport). `create_app`'s lifespan
starts every background monitor as an asyncio task and cancels them on exit.
"""

from __future__ import annotations
import asyncio
import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from ama.archive import Archive
from ama.cdarchive import CdArchiver
from ama.cdrip import CdRipper, CdTracks
from ama.config import Config
from ama.db import Database
from ama.discs import DiscStore
from ama.drive import DriveMonitor, DriveProbe, default_probe
from ama.events import EventBus
from ama.moviearchive import MovieArchiver, Movies
from ama.moviereview import Thumbnailer
from ama.musicbrainz import USER_AGENT, MusicBrainz
from ama.nas import NasMonitor
from ama.plex import Plex
from ama.proc import Runner, Streamer, run, stream
from ama.tmdb import Tmdb
from ama.tools import ToolLookup, Tools
from ama.video_rip import VideoRipper
from ama.web import STATIC_DIR, auth, discs_pages, movie_review_pages, pages, review_pages


@dataclass
class Services:
    config: Config
    db: Database
    bus: EventBus
    drive: DriveMonitor
    nas: NasMonitor
    discs: DiscStore
    cd: CdRipper
    video_rip: VideoRipper
    tools: Tools
    archive: Archive
    musicbrainz: MusicBrainz
    cd_archive: CdArchiver
    movie_archive: MovieArchiver
    tmdb: Tmdb
    thumbnails: Thumbnailer

    def background_tasks(self) -> list[Callable[[], object]]:
        """Coroutine functions run for the app's lifetime. Add new monitors/workers here."""
        return [self.drive.run, self.nas.run, self.cd.run, self.video_rip.run,
                self.tools.run, self.cd_archive.run, self.movie_archive.run,
                self.thumbnails.run]


def build_services(
    cfg: Config,
    probe: DriveProbe | None = None,
    runner: Runner = run,
    nas_exists: Callable[[str], bool] = os.path.isdir,
    streamer: Streamer = stream,
    tool: ToolLookup | None = None,
    make_tools: Callable[[EventBus], Tools] | None = None,
    http: httpx.Client | None = None,
    disc_root: Callable[[], Path | None] | None = None,
) -> Services:
    cfg.paths.scratch.mkdir(parents=True, exist_ok=True)
    bus = EventBus()
    db = Database(cfg.paths.state_db)
    tools = make_tools(bus) if make_tools else Tools(cfg.tools, bus, runner=runner)
    tool = tool or tools.path
    drive = DriveMonitor(probe or default_probe(cfg.drive.letter or None), bus,
                         interval=cfg.drive.poll_seconds)
    discs = DiscStore(db, cfg.paths.scratch)
    http = http or httpx.Client(timeout=30)
    http.headers["User-Agent"] = USER_AGENT
    nas = NasMonitor(cfg.nas, bus, runner=runner, exists=nas_exists)
    cd_tracks = CdTracks(db)
    archive = Archive(Path(cfg.nas.unc))
    mb = MusicBrainz(http)
    tmdb = Tmdb(http, cfg.tmdb.api_key)
    plex = Plex(cfg.plex, http, archive.root)
    if disc_root is None:
        def disc_root() -> Path | None:
            device = drive.device()
            return Path(device + "\\") if device else None
    return Services(
        config=cfg,
        db=db,
        bus=bus,
        drive=drive,
        nas=nas,
        tools=tools,
        discs=discs,
        cd=CdRipper(cfg.cd, drive, discs, cd_tracks, bus, streamer=streamer,
                    tool=tool, interval=cfg.drive.poll_seconds),
        video_rip=VideoRipper(drive, discs, bus, makemkvcon=lambda: tool("makemkvcon"),
                              streamer=streamer, disc_root=disc_root),
        archive=archive,
        musicbrainz=mb,
        cd_archive=CdArchiver(discs, cd_tracks, nas, mb, archive, plex, bus,
                              interval=cfg.drive.poll_seconds),
        movie_archive=MovieArchiver(discs, Movies(db), tmdb, nas,
                                    archive, plex, bus, cfg.encode.cq, tool, streamer,
                                    interval=cfg.drive.poll_seconds,
                                    retry_seconds=cfg.nas.retry_seconds),
        tmdb=tmdb,
        thumbnails=Thumbnailer(discs, tool, streamer, interval=cfg.drive.poll_seconds),
    )


def create_app(services: Services) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        tasks = [asyncio.create_task(fn()) for fn in services.background_tasks()]
        try:
            yield
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.services = services
    auth.install(app, services)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(pages.router)
    app.include_router(discs_pages.router)
    app.include_router(review_pages.router)
    app.include_router(movie_review_pages.router)
    return app
