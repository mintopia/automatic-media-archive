"""Setup (ADR 0016): with no settings file, AMA serves only this wizard, on 127.0.0.1.

Each step is a module in `ama.setup.steps` exposing `STEP`, found at startup and run in
`Step.order`; adding a step is adding a module (see that package for the order numbers).
A step owns its form fields (prefilled from `Step.defaults`), checks them, says what they
put in the settings file (`Step.settings`) and how they read on the Ready step
(`Step.summary`). Finishing writes the file once with `SettingsFile.create` (ADR 0008);
an existing file means Setup is done, so it never runs again. Once it's written, a step may
give the finished page cookies to set (`Step.cookies`: the remote step signs the browser in).
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
import secrets
import threading
import webbrowser
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from ama.config import SETUP_HOST, WebConfig
from ama.setup.machine import Machine
from ama.settings import SettingsFile, SettingsRejected
from ama.web import STATIC_DIR, TEMPLATES, auth

log = logging.getLogger(__name__)

HOST = SETUP_HOST

Values = Mapping[str, str]  # every step's form fields, by name (names are unique across steps)


@dataclass(frozen=True)
class Draft:
    """What steps put in the new settings file: `SettingsFile.create`'s arguments."""

    changes: dict[str, str] = field(default_factory=dict)  # dotted key -> typed text
    libraries: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class Step:
    slug: str  # its page: /setup/<slug>
    title: str  # the page's heading and its name in the step list
    order: int  # where it comes (ama.setup.steps lists the numbers in use)
    template: str  # the step's body, inside the page's form
    defaults: Callable[[Path], dict[str, str]] = lambda config: {}  # field -> prefilled
    check: Callable[[Values], dict[str, str]] = lambda values: {}  # field -> what to fix
    settings: Callable[[Values], Draft] = lambda values: Draft()
    summary: Callable[[Values], list[tuple[str, str]]] = lambda values: []  # Ready's rows
    # name -> value, for the finished page to set; called once the file is written
    cookies: Callable[[Values, Path], dict[str, str]] = lambda values, config: {}
    button: str = "Continue"


def discover() -> list[Step]:
    """Every `STEP` in `ama.setup.steps`, in order."""
    from ama.setup import steps
    found = [importlib.import_module(f"{steps.__name__}.{m.name}").STEP
             for m in pkgutil.iter_modules(steps.__path__)]
    return sorted(found, key=lambda s: s.order)


class SetupDone(Exception):
    """The settings file exists: Setup has nothing to do."""


class Setup:
    """The wizard's state: the values typed so far, and whether the file is written."""

    def __init__(self, config: Path, steps: Sequence[Step] | None = None,
                 machine: Machine | None = None) -> None:
        self.config = Path(config)
        self.machine = machine if machine is not None else Machine.this_pc()
        self.steps = list(steps if steps is not None else discover())
        self.values: dict[str, str] = {}
        for step in self.steps:
            self.values |= step.defaults(self.config)
        self.boot = secrets.token_hex(8)  # the finished page waits for a different one
        self.finished = threading.Event()
        self.cookies: dict[str, str] = {}  # what the finished page sets (Step.cookies)

    def step(self, slug: str) -> Step | None:
        return next((s for s in self.steps if s.slug == slug), None)

    def neighbours(self, step: Step) -> tuple[Step | None, Step | None]:
        i = self.steps.index(step)
        return (self.steps[i - 1] if i else None,
                self.steps[i + 1] if i + 1 < len(self.steps) else None)

    def submit(self, step: Step, form: Values) -> dict[str, str]:
        """Keep the step's fields from `form`; what to fix in them (empty = go on)."""
        for name in step.defaults(self.config):
            if name in form:
                self.values[name] = str(form[name]).strip()
        return step.check(self.values)

    def finish(self) -> Step | None:
        """Write the settings file; or the first step whose values need fixing. Raises
        SetupDone (and counts as finished) if the file is already there."""
        if self.config.exists():
            self.finished.set()
            raise SetupDone
        draft = Draft()
        for step in self.steps:
            if step.check(self.values):
                return step
            part = step.settings(self.values)
            draft.changes.update(part.changes)
            draft.libraries.extend(part.libraries)
        try:
            SettingsFile(self.config).create(draft.changes, draft.libraries)
        except FileExistsError:
            self.finished.set()
            raise SetupDone from None
        log.info("setup: wrote %s", self.config)
        for step in self.steps:
            self.cookies |= step.cookies(self.values, self.config)
        self.finished.set()
        return None


def run_setup(config: Path, port: int = WebConfig().port,
              open_url: Callable[[str], object] = webbrowser.open,
              control_token: str = "", machine: Machine | None = None) -> bool:
    """Serve Setup on 127.0.0.1:`port` and open it in the browser; return once the settings
    file is written (True) or Setup is stopped first: the tray's Quit, Ctrl+C (False).
    AMA's tools start downloading straight away."""
    setup = Setup(config, machine=machine)
    setup.machine.start()
    app = create_setup_app(setup, control_token)
    server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=port, log_config=None,
                                           timeout_graceful_shutdown=3))
    stopping = threading.Event()

    def stop() -> None:
        stopping.set()
        server.should_exit = True

    app.state.on_quit = stop

    def hand_over() -> None:  # after the finished page is on its way to the browser
        while not stopping.is_set():
            if setup.finished.wait(0.2):
                threading.Timer(0.5, stop).start()
                return

    def announce() -> None:
        while not server.started:
            if stopping.wait(0.05):
                return
        bound = server.servers[0].sockets[0].getsockname()[1]
        url = f"http://{HOST}:{bound}/"
        log.info("setup: no settings file at %s; Setup is at %s", config, url)
        open_url(url)

    for watcher in (hand_over, announce):
        threading.Thread(target=watcher, daemon=True).start()
    try:
        server.run()
    finally:
        stopping.set()
    return setup.finished.is_set()


def create_setup_app(setup: Setup, control_token: str = "") -> FastAPI:
    """The Setup pages and nothing else: any other path leads to the first step.
    `control_token`: the supervisor's tray may Quit with it (`ama.tray`)."""
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.on_quit = lambda: None  # run_setup stops the server
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.post("/control/quit")
    def control_quit(request: Request) -> Response:
        if not (control_token and auth.is_control(request, control_token)):
            return Response(status_code=403)
        request.app.state.on_quit()
        return Response(status_code=204)
    first = f"/setup/{setup.steps[0].slug}"

    def page(request: Request, step: Step, errors: Mapping[str, str] | None = None,
             status: int = 200) -> Response:
        back, _ = setup.neighbours(step)
        return TEMPLATES.TemplateResponse(request, "setup/step.html", {
            "step": step, "steps": setup.steps, "values": setup.values,
            "errors": errors or {}, "back": back, "config": setup.config,
            "machine": setup.machine,
            "summary": [row for s in setup.steps for row in s.summary(setup.values)],
        }, status_code=status)

    def done(request: Request, status: int = 200) -> Response:
        return TEMPLATES.TemplateResponse(request, "setup/finished.html", {
            "boot": setup.boot, "config": setup.config}, status_code=status)

    @app.get("/boot")
    def boot() -> Response:
        return JSONResponse({"boot": setup.boot}, headers={"Cache-Control": "no-store"})

    @app.get("/setup-downloads", response_class=HTMLResponse)
    def downloads(request: Request) -> Response:  # Ready polls this while they're under way
        return TEMPLATES.TemplateResponse(request, "setup/downloads.html",
                                          {"machine": setup.machine})

    @app.post("/setup-downloads/retry")
    def retry_downloads() -> Response:
        setup.machine.start()
        return RedirectResponse(f"/setup/{setup.steps[-1].slug}", status_code=303)

    @app.get("/setup/{slug}", response_class=HTMLResponse)
    def show(request: Request, slug: str) -> Response:
        step = setup.step(slug)
        if step is None:
            return RedirectResponse(first, status_code=303)
        return page(request, step)

    @app.post("/setup/{slug}", response_class=HTMLResponse)
    async def submit(request: Request, slug: str) -> Response:
        step = setup.step(slug)
        if step is None:
            return RedirectResponse(first, status_code=303)
        form = {k: v for k, v in (await request.form()).items() if isinstance(v, str)}
        errors = setup.submit(step, form)
        if errors:
            return page(request, step, errors, status=422)
        _, after = setup.neighbours(step)
        if after is not None:
            return RedirectResponse(f"/setup/{after.slug}", status_code=303)
        if setup.machine.busy:
            return page(request, step, {"": "AMA is still downloading its tools. Setup "
                                        "finishes once they're in."}, status=422)
        try:
            stuck = setup.finish()
        except SetupDone:
            return done(request, status=409)
        except SettingsRejected as e:
            return page(request, step, {"": str(e)}, status=422)
        if stuck is not None:
            return page(request, stuck, stuck.check(setup.values), status=422)
        response = done(request)
        for name, value in setup.cookies.items():
            response.set_cookie(name, value, **auth.COOKIE_OPTIONS)
        return response

    @app.api_route("/{path:path}", methods=["GET", "POST"])
    def elsewhere(path: str) -> Response:
        return RedirectResponse(first, status_code=303)

    return app
