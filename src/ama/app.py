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
from ama.cdguess import CdPicks, Guesser
from ama.cdrip import CdRipper, CdTracks
from ama.covers import DIR as COVERS_DIR, Covers
from ama.app_events import AppEvents
from ama.config import Config, secret_values
from ama.db import Database
from ama.jobs import JobStore
from ama.encoder import Encoder
from ama.encoder_probe import EncoderProbe
from ama.drive import DriveMonitor, DriveProbe, default_probe
from ama.events import EventBus
from ama.film_guess import FilmGuesses
from ama.media import MediaStore
from ama.extras import STILLS, Extras
from ama.moviearchive import MovieArchiver, Movies
from ama.moviereview import Thumbnailer
from ama.musicbrainz import USER_AGENT, MusicBrainz
from ama.nas import NasMonitor
from ama.notify import Notifier, channels
from ama.pause import Pause
from ama.problems import Problems
from ama.plex import Plex
from ama.proc import Runner, Streamer, run, stream
from ama.repeat import RepeatGuard
from ama.restart import Busy, Restarter
from ama.runs import LogPruner, Runs
from ama.scratch import DiskUsageFn, ScratchGate
from ama.settings import Settings
from ama.sets import DiscSets
from ama.tmdb import Tmdb
from ama.tools import ToolLookup, Tools
from ama.tvarchive import TvArchiver, TvTitles
from ama.video_rip import VideoRipper
from ama.web import (STATIC_DIR, auth, cd_pick_pages, jobs_pages, extras_pages, guess_pages,
                     history_pages, logs_pages, movie_review_pages, pages,
                     repeat_pages, review_pages, scratch_pages, set_review_pages,
                     restart_pages, settings_libraries, settings_pages, tv_review_pages)
from ama.web.current_rip import current_rip


@dataclass
class Services:
    config: Config
    db: Database
    bus: EventBus
    drive: DriveMonitor
    nas: NasMonitor
    jobs: JobStore
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
    film_guesses: FilmGuesses  # a video Job's Best guess
    backfill: Backfill
    pause: Pause
    plex: Plex
    http: httpx.Client
    encoders: EncoderProbe  # which encoders pass a test encode (ADR 0010)
    problems: Problems  # why Jobs can't move on: Waiting lines and Now banners
    restart: Restarter
    runs: Runs  # Logs: every Job's Run and each app event's, with Step output
    app_events: AppEvents  # startup, NAS and tool events as Runs
    log_pruner: LogPruner  # removes Step output older than logs.keep_days (#34)
    settings: Settings | None = None  # set by build_services; ama.toml vs what's running

    def apply_live(self, cfg: Config) -> None:
        """Hand the settings.LIVE_TABLES values in `cfg` to the code that reads them."""
        if cfg.encode != self.config.encode:
            self.encoders.request()  # test the encoders again on save (ADR 0010)
        if cfg.logs != self.config.logs:
            self.log_pruner.request()  # a shorter keep applies at once
        self.config = cfg
        self.cd.cfg = cfg.cd
        self.movie_archive.encoder.cfg = cfg.encode
        self.tmdb.api_key = cfg.tmdb.api_key
        self.plex.cfg = cfg.plex
        self.archive.libraries = cfg.libraries
        self.notifier.channels = channels(cfg, self.http)

    def background_tasks(self) -> list[Callable[[], object]]:
        """Coroutine functions run for the app's lifetime. Add new monitors/workers here."""
        return [self.problems.run, self.runs.run, self.log_pruner.run, self.app_events.run,
                self.drive.run,
                self.nas.run, self.cd.run, self.video_rip.run,
                self.tools.run, self.tools.watch_makemkv,
                self.cd_archive.run, self.movie_archive.run,
                self.thumbnails.run, self.tv_archive.run, self.notifier.run,
                self.backfill.run, self.restart.run, self.encoders.run,
                *([self.settings.run] if self.settings else [])]


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
    problems = Problems(bus)
    db = Database(cfg.paths.state_db)
    tools = make_tools(bus) if make_tools else Tools(cfg.tools, bus, runner=runner)
    tool = tool or tools.path
    drive = DriveMonitor(probe or default_probe(cfg.drive.letter or None), bus,
                         interval=cfg.drive.poll_seconds)
    # Logs: masks whatever secrets the running settings hold (`services` is set below).
    runs = Runs(db, bus, secrets=lambda: secret_values(services.config))
    runs.recover()
    runs.tool_label = tools.label
    jobs = JobStore(db, cfg.paths.scratch, runs=runs)
    scratch = ScratchGate(cfg.scratch, cfg.paths.scratch, drive, bus, disk_usage)
    http = http or httpx.Client(timeout=30)
    http.headers["User-Agent"] = USER_AGENT
    nas = NasMonitor(cfg.nas, bus, runner=runner, exists=nas_exists)
    cd_tracks = CdTracks(db)
    archive = Archive(Path(cfg.nas.unc), cfg.libraries)
    mb = MusicBrainz(http)
    covers = Covers(cfg.paths.state_db.parent / COVERS_DIR, mb)
    media = MediaStore(db)
    tmdb = Tmdb(http, cfg.tmdb.api_key)
    film_guesses = FilmGuesses(db, tmdb, covers)
    cd_picks = CdPicks(db)
    plex = Plex(cfg.plex, http, archive, problems)
    repeat = RepeatGuard(db, jobs, drive, bus, archive.root)
    pause = Pause(db, bus)
    tv_titles = TvTitles(db)
    restart = Restarter(lambda: busy(services), bus)
    encoder = Encoder(jobs, bus, cfg.encode, tool, streamer, hold=restart.holding)
    movie_archive = MovieArchiver(jobs, Movies(db), tmdb, nas, archive, plex, bus, encoder,
                                  streamer, interval=cfg.drive.poll_seconds,
                                  retry_seconds=cfg.nas.retry_seconds, claimed=tv_titles.has,
                                  extras=Extras(db, cfg.paths.state_db.parent / STILLS),
                                  media=media, covers=covers, picked=film_guesses.picked,
                                  problems=problems)
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
        jobs=jobs,
        cd=CdRipper(cfg.cd, drive, jobs, cd_tracks, bus, streamer=streamer,
                    tool=tool, interval=cfg.drive.poll_seconds, repeat=repeat,
                    scratch=scratch, pause=pause, picks=cd_picks,
                    guesser=Guesser(mb, covers), hold=restart.holding),
        video_rip=VideoRipper(drive, jobs, bus, makemkvcon=lambda: tool("makemkvcon"),
                              streamer=streamer, repeat=repeat, scratch=scratch,
                              pause=pause, disc_root=disc_root,
                              guesses=film_guesses, hold=restart.holding),
        archive=archive,
        musicbrainz=mb,
        cd_archive=CdArchiver(jobs, cd_tracks, nas, mb, archive, plex, bus,
                              interval=cfg.drive.poll_seconds, covers=covers, media=media,
                              picked=cd_picks.get, problems=problems),
        movie_archive=movie_archive,
        tmdb=tmdb,
        thumbnails=Thumbnailer(jobs, tool, streamer, interval=cfg.drive.poll_seconds),
        repeat=repeat,
        scratch=scratch,
        tv_archive=TvArchiver(jobs, tv_titles, encoder, nas, archive, plex, bus,
                              interval=cfg.drive.poll_seconds,
                              retry_seconds=cfg.nas.retry_seconds, tmdb=tmdb, media=media,
                              covers=covers, problems=problems),
        notifier=Notifier(jobs, bus, channels(cfg, http), problems),
        sets=DiscSets(db),
        covers=covers,
        media=media,
        film_guesses=film_guesses,
        backfill=Backfill(db, jobs, media, mb, covers, tmdb, movie_archive.movies,
                          tv_titles),
        pause=pause,
        plex=plex,
        http=http,
        encoders=EncoderProbe(bus, tool, streamer, lambda: services.config.encode),
        problems=problems,
        restart=restart,
        runs=runs,
        app_events=AppEvents(runs, bus, nas, tools, config_path),
        log_pruner=LogPruner(runs, lambda: services.config.logs.keep_days),
    )
    services.settings = Settings(config_path, cfg, services.apply_live)
    services.encoders.log = services.app_events  # each encoder test is a Step in Logs
    return services


def busy(services: Services) -> Busy:
    """The Rip and Encode a restart would cut off."""
    rip = current_rip(services)
    encode = services.movie_archive.encoder.current  # one Encoder, shared with TV
    etas = [e for e in (rip.cd.eta_seconds if rip and rip.cd else None,
                        rip.progress.eta_s if rip and rip.progress else None,
                        encode.progress.eta_s if encode else None) if e is not None]
    return Busy(rip.name if rip else None, 1 if encode else 0, max(etas) if etas else None)


def create_app(services: Services, control_token: str = "") -> FastAPI:
    """`control_token`: the supervisor's tray gets past the password with it (`ama.tray`)."""
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
    app.state.control_token = control_token
    auth.install(app, services, control_token)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(pages.router)
    app.include_router(jobs_pages.router)
    app.include_router(guess_pages.router)
    app.include_router(cd_pick_pages.router)
    app.include_router(review_pages.router)
    app.include_router(movie_review_pages.router)
    app.include_router(extras_pages.router)
    app.include_router(tv_review_pages.router)
    app.include_router(set_review_pages.router)
    app.include_router(repeat_pages.router)
    app.include_router(scratch_pages.router)
    app.include_router(history_pages.router)
    app.include_router(settings_libraries.router)  # before settings_pages' catch-all
    app.include_router(settings_pages.router)
    app.include_router(restart_pages.router)
    app.include_router(logs_pages.router)
    return app
