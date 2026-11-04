"""Wiring: build the long-lived services, and the FastAPI app that serves them.

`build_services` is the one place real OS/process adapters are chosen; tests
pass fakes for `probe`, `runner` and `nas_exists`. `create_app`'s lifespan
starts every background monitor as an asyncio task and cancels them on exit.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from ama import tools
from ama.cdrip import CdRipper, CdTracks
from ama.config import Config
from ama.db import Database
from ama.discs import Discs
from ama.drive import DriveMonitor, DriveProbe, default_probe
from ama.events import EventBus
from ama.nas import NasMonitor
from ama.proc import Runner, Streamer, run, stream
from ama.tools import ToolLookup
from ama.web import STATIC_DIR, auth, discs_pages, pages


@dataclass
class Services:
    config: Config
    db: Database
    bus: EventBus
    drive: DriveMonitor
    nas: NasMonitor
    discs: Discs
    cd: CdRipper

    def background_tasks(self) -> list[Callable[[], object]]:
        """Coroutine functions run for the app's lifetime. Add new monitors/workers here."""
        return [self.drive.run, self.nas.run, self.cd.run]


def build_services(
    cfg: Config,
    probe: DriveProbe | None = None,
    runner: Runner = run,
    nas_exists: Callable[[str], bool] = os.path.isdir,
    streamer: Streamer = stream,
    tool: ToolLookup | None = None,
) -> Services:
    cfg.paths.scratch.mkdir(parents=True, exist_ok=True)
    bus = EventBus()
    db = Database(cfg.paths.state_db)
    drive = DriveMonitor(probe or default_probe(cfg.drive.letter or None), bus,
                         interval=cfg.drive.poll_seconds)
    discs = Discs(db, cfg.paths.scratch)
    return Services(
        config=cfg,
        db=db,
        bus=bus,
        drive=drive,
        nas=NasMonitor(cfg.nas, bus, runner=runner, exists=nas_exists),
        discs=discs,
        cd=CdRipper(cfg.cd, drive, discs, CdTracks(db), bus, streamer=streamer,
                    tool=tool or tools.lookup(cfg.tools), interval=cfg.drive.poll_seconds),
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
    return app
