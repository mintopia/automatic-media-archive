"""Wiring: build the long-lived services, and the FastAPI app that serves them.

`build_services` is the one place real OS/process adapters are chosen; tests
pass fakes for `probe`, `runner`, `streamer`, `tool`, `make_tools`, `nas_exists`
and `http` (an httpx client, e.g. over a MockTransport). `create_app`'s lifespan
starts every background monitor as an asyncio task and cancels them on exit.
"""

from __future__ import annotations
import asyncio
import os
import shutil
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from ama.archive import Archive
from ama.backfill import Backfill
from ama.cdarchive import CdArchiver
from ama.cdguess import Guesser
from ama.cdrip import CdRipper, CdTracks
from ama.covers import DIR as COVERS_DIR, Covers
from ama.config import Config
from ama.db import Database
from ama.discs import DiscStore
from ama.encoder import Encoder
from ama.drive import DriveMonitor, DriveProbe, default_probe
from ama.events import EventBus
from ama.media import MediaStore, film_guess
from ama.extras import STILLS, Extras
from ama.moviearchive import MovieArchiver, Movies
from ama.moviereview import Thumbnailer
from ama.musicbrainz import USER_AGENT, MusicBrainz
from ama.nas import NasMonitor
from ama.notify import Notifier, channels
from ama.plex import Plex
from ama.proc import Runner, Streamer, run, stream
from ama.repeat import RepeatGuard
from ama.scratch import DiskUsageFn, ScratchGate
from ama.settings import Settings
from ama.sets import DiscSets
from ama.tmdb import Tmdb
from ama.tools import ToolLookup, Tools
from ama.tvarchive import TvArchiver, TvTitles
from ama.video_rip import VideoRipper
from ama.web import (STATIC_DIR, auth, discs_pages, extras_pages, history_pages,
                     movie_review_pages, pages,
                     repeat_pages, review_pages, scratch_pages, set_review_pages,
                     settings_pages, tv_review_pages)


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
    repeat: RepeatGuard
    scratch: ScratchGate
    tv_archive: TvArchiver
    notifier: Notifier
    sets: DiscSets
    covers: Covers
    media: MediaStore
    backfill: Backfill
    plex: Plex
    http: httpx.Client
    settings: Settings | None = None  # set by build_services; ama.toml vs what's running

    def apply_live(self, cfg: Config) -> None:
        """Hand the settings.LIVE_TABLES values in `cfg` to the code that reads them."""
        self.config = cfg
        self.cd.cfg = cfg.cd
        self.movie_archive.encoder.cq = cfg.encode.cq
        self.tmdb.api_key = cfg.tmdb.api_key
        self.plex.cfg = cfg.plex
        self.notifier.channels = channels(cfg, self.http)

    def background_tasks(self) -> list[Callable[[], object]]:
        """Coroutine functions run for the app's lifetime. Add new monitors/workers here."""
        return [self.drive.run, self.nas.run, self.cd.run, self.video_rip.run,
                self.tools.run, self.cd_archive.run, self.movie_archive.run,
                self.thumbnails.run, self.tv_archive.run, self.notifier.run,
                self.backfill.run, *([self.settings.run] if self.settings else [])]


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
    disk_usage: DiskUsageFn = shutil.disk_usage,
    config_path: Path | None = None,
) -> Services:
    cfg.paths.scratch.mkdir(parents=True, exist_ok=True)
    bus = EventBus()
    db = Database(cfg.paths.state_db)
    tools = make_tools(bus) if make_tools else Tools(cfg.tools, bus, runner=runner)
    tool = tool or tools.path
    drive = DriveMonitor(probe or default_probe(cfg.drive.letter or None), bus,
                         interval=cfg.drive.poll_seconds)
    discs = DiscStore(db, cfg.paths.scratch)
    scratch = ScratchGate(cfg.scratch, cfg.paths.scratch, drive, bus, disk_usage)
    http = http or httpx.Client(timeout=30)
    http.headers["User-Agent"] = USER_AGENT
    nas = NasMonitor(cfg.nas, bus, runner=runner, exists=nas_exists)
    cd_tracks = CdTracks(db)
    archive = Archive(Path(cfg.nas.unc))
    mb = MusicBrainz(http)
    covers = Covers(cfg.paths.state_db.parent / COVERS_DIR, mb)
    media = MediaStore(db)
    tmdb = Tmdb(http, cfg.tmdb.api_key)
    plex = Plex(cfg.plex, http, archive.root)
    repeat = RepeatGuard(db, discs, drive, bus, archive.root)
    tv_titles = TvTitles(db)
    encoder = Encoder(discs, bus, cfg.encode.cq, tool, streamer)
    movie_archive = MovieArchiver(discs, Movies(db), tmdb, nas, archive, plex, bus, encoder,
                                  streamer, interval=cfg.drive.poll_seconds,
                                  retry_seconds=cfg.nas.retry_seconds, claimed=tv_titles.has,
                                  extras=Extras(db, cfg.paths.state_db.parent / STILLS),
                                  media=media, covers=covers)
    if disc_root is None:
        def disc_root() -> Path | None:
            device = drive.device()
            return Path(device + "\\") if device else None
    services = Services(
        config=cfg,
        db=db,
        bus=bus,
        drive=drive,
        nas=nas,
        tools=tools,
        discs=discs,
        cd=CdRipper(cfg.cd, drive, discs, cd_tracks, bus, streamer=streamer,
                    tool=tool, interval=cfg.drive.poll_seconds, repeat=repeat,
                    scratch=scratch, guesser=Guesser(mb, covers)),
        video_rip=VideoRipper(drive, discs, bus, makemkvcon=lambda: tool("makemkvcon"),
                              streamer=streamer, repeat=repeat, scratch=scratch,
                              disc_root=disc_root,
                              guess=lambda label: film_guess(tmdb, covers, label)),
        archive=archive,
        musicbrainz=mb,
        cd_archive=CdArchiver(discs, cd_tracks, nas, mb, archive, plex, bus,
                              interval=cfg.drive.poll_seconds, covers=covers, media=media),
        movie_archive=movie_archive,
        tmdb=tmdb,
        thumbnails=Thumbnailer(discs, tool, streamer, interval=cfg.drive.poll_seconds),
        repeat=repeat,
        scratch=scratch,
        tv_archive=TvArchiver(discs, tv_titles, encoder, nas, archive, plex, bus,
                              interval=cfg.drive.poll_seconds,
                              retry_seconds=cfg.nas.retry_seconds, tmdb=tmdb, media=media,
                              covers=covers),
        notifier=Notifier(discs, bus, channels(cfg, http)),
        sets=DiscSets(db),
        covers=covers,
        media=media,
        backfill=Backfill(db, discs, media, mb, covers, tmdb, movie_archive.movies,
                          tv_titles),
        plex=plex,
        http=http,
    )
    services.settings = Settings(config_path, cfg, services.apply_live)
    return services


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
    app.include_router(extras_pages.router)
    app.include_router(tv_review_pages.router)
    app.include_router(set_review_pages.router)
    app.include_router(repeat_pages.router)
    app.include_router(scratch_pages.router)
    app.include_router(history_pages.router)
    app.include_router(settings_pages.router)
    return app
