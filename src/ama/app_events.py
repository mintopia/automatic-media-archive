"""App events as Runs in Logs (GLOSSARY: Run): startup, the NAS dropping or coming back, and
tools being fetched or fixed after startup.

`AppEvents` watches what the monitors already know (`NasMonitor.status`, `Tools.status`)
rather than being told: each watched thing is an `Item` whose `observe()` says how it is
now. At startup each Item is a Step of the "AMA started" Run until it settles; after that,
trouble opens a Run of its own (NAS, Tools) that ends when the trouble does.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from ama.events import EventBus
from ama.nas import NasConnected, NasConnecting, NasMonitor, NasUnreachable
from ama.runs import RunKind, Runs
from ama.tools import (Pin, ToolDownloading, ToolFailed, ToolNotFound, ToolPending, ToolReady,
                       Tools, makemkv_headline)

POLL_SECONDS = 1.0  # also woken by every bus event


class Seen(StrEnum):
    PENDING = "pending"  # not known yet
    BUSY = "busy"        # being fetched or connected
    OK = "ok"
    PROBLEM = "problem"


@dataclass(frozen=True)
class Observation:
    seen: Seen
    line: str = ""    # said in the Step's output when it changes
    result: str = ""  # the Step's short result


@dataclass(frozen=True)
class Item:
    key: str
    step: str                 # the Step's name: "Connect to the NAS"
    kind: RunKind             # the Run it gets after startup
    observe: Callable[[], Observation]
    trouble: Callable[[bool], str]  # a later Run's title; arg: it was fine before
    fixed: Callable[[bool], str]    # its title once fixed; arg: it was fine before
    later_step: str = ""      # the Step a later Run works on ("Reconnect"); default `step`


def nas_item(nas: NasMonitor) -> Item:
    def observe() -> Observation:
        unc = nas.cfg.unc
        match nas.status:
            case NasConnecting():
                return Observation(Seen.PENDING)
            case NasConnected():
                return Observation(Seen.OK, f"Connected to {unc}", unc)
            case NasUnreachable(detail=detail):
                return Observation(Seen.PROBLEM, f"{unc} didn't answer: {detail}",
                                   f"{unc} isn't reachable · filing waits")
        return Observation(Seen.PENDING)

    return Item("nas", "Connect to the NAS", RunKind.NAS, observe,
                trouble=lambda was_ok: "Lost the NAS" if was_ok else "Couldn't reach the NAS",
                fixed=lambda was_ok: ("Lost the NAS, then reconnected" if was_ok
                                      else "Reached the NAS"),
                later_step="Reconnect")


def makemkv_item(tools: Tools) -> Item:
    def observe() -> Observation:
        status = tools.status("makemkvcon")
        match status:
            case ToolPending():
                return Observation(Seen.PENDING)
            case ToolReady(version=v, source=source):
                return Observation(Seen.OK, f"MakeMKV v{v} is ready ({source})",
                                   f"Your copy · {v}, registered")
        headline = makemkv_headline(status)
        return Observation(Seen.PROBLEM, headline, headline.rstrip("."))

    return Item("makemkv", "Check MakeMKV", RunKind.TOOLS, observe,
                trouble=lambda _: "MakeMKV isn't ready", fixed=lambda _: "MakeMKV is ready")


def pin_item(tools: Tools, pin: Pin) -> Item:
    """One download (ffmpeg brings ffprobe): its members' statuses, the worst first."""
    seen_download = {"yes": False}

    def observe() -> Observation:
        statuses = [tools.status(m.name) for m in pin.members]
        for st in statuses:
            if isinstance(st, ToolNotFound):
                return Observation(Seen.PROBLEM, f"Can't find {st.path} (set in [tools])",
                                   f"Can't find {st.path.name}")
            if isinstance(st, ToolFailed):
                return Observation(Seen.PROBLEM, f"Couldn't download {st.label}: {st.detail}",
                                   f"Couldn't download {st.label}")
        for st in statuses:
            if isinstance(st, ToolDownloading):
                seen_download["yes"] = True
                return Observation(Seen.BUSY, f"Downloading {st.label}")
            if isinstance(st, ToolPending):
                return Observation(Seen.PENDING)
        ready = [st for st in statuses if isinstance(st, ToolReady)]
        if ready and all(st.source == "config" for st in ready):
            return Observation(Seen.OK, f"Using your copy: {ready[0].path}", "Your copy")
        how = "downloaded, checksum matches" if seen_download["yes"] \
            else "already there, checksum matches"
        return Observation(Seen.OK, f"{pin.label} ready: {how}", f"AMA's copy · {pin.version} {how}")

    return Item(pin.key, f"Get {pin.key}", RunKind.TOOLS, observe,
                trouble=lambda _: f"Couldn't download {pin.label}",
                fixed=lambda _: f"Downloaded {pin.label}")


class _Watch:
    """One Item's place: its startup Step, then any later Run it has open."""

    def __init__(self, item: Item) -> None:
        self.item = item
        self.last: Observation | None = None
        self.was_ok = False
        self.startup_step: int | None = None
        self.run: int | None = None
        self.run_step: int | None = None


class AppEvents:
    def __init__(self, runs: Runs, bus: EventBus, nas: NasMonitor, tools: Tools,
                 config_path: Path | None = None, test_encoders: bool = True) -> None:
        self._runs = runs
        # (no ffmpeg pin means no ffmpeg to wait for: tests only)
        self.test_encoders = test_encoders and any(p.key == "ffmpeg" for p in tools.pins)
        self._startup_tests: int | None = None  # the startup test, while it runs
        self._tests_failed = False
        self._bus = bus
        self._config_path = config_path
        self.items = [nas_item(nas), makemkv_item(tools),
                      *(pin_item(tools, p) for p in tools.pins)]
        self._watches: list[_Watch] = []
        self.startup: int | None = None  # the "AMA started" Run, while it's open
        # The encoder test (encoder_probe, which writes it through begin/line/end below):
        # its startup Step until the first test takes it, and later tests' own Runs.
        self._encoders_step: int | None = None
        self._test_runs: dict[int, int] = {}  # Step -> its own Run (tests after startup)

    def start(self) -> None:
        """Open the "AMA started" Run: settings read, then a Step per Item."""
        self.startup = self._runs.start_run(RunKind.APP, "AMA started", item="startup")
        settings = self._runs.begin(self.startup, "settings", "Read settings")
        where = self._config_path.name if self._config_path else "Settings"
        self._runs.line(settings, f"Read {self._config_path or 'the settings'}: no problems found")
        self._runs.end(settings, result=f"{where} · no problems found")
        self._watches = []
        for item in self.items:
            w = _Watch(item)
            w.startup_step = self._runs.begin(self.startup, item.key, item.step)
            self._watches.append(w)
        if self.test_encoders:
            self._encoders_step = self._runs.begin(self.startup, "encoders", "Test encoders",
                                                   tool="ffmpeg")

    # --- the encoder test (encoder_probe.ProbeLog) ---

    def begin(self) -> int:
        """A test run starts: the startup Step if it's still waiting, else a Run of its own."""
        if self._encoders_step is not None and self.startup is not None:
            step, self._encoders_step = self._encoders_step, None
            self._startup_tests = step
            return step
        run = self._runs.start_run(RunKind.TOOLS, "Tested the encoders", item="encoders")
        step = self._runs.begin(run, "encoders", "Test encoders", tool="ffmpeg")
        self._test_runs[step] = run
        return step

    def line(self, step: int, text: str, error: bool = False) -> None:
        self._runs.line(step, text, error)

    def end(self, step: int, failed: bool, result: str) -> None:
        self._runs.end(step, failed=failed, result=result)
        run = self._test_runs.pop(step, None)
        if run is not None:
            self._runs.finish_run(run, failed=failed)
        elif step == self._startup_tests:
            self._startup_tests = None
            self._tests_failed = failed
            self.check()

    def _tests_waiting(self) -> bool:
        """The startup encoder test hasn't run (or finished) yet."""
        if self._startup_tests is not None:
            return True
        if self._encoders_step is None:
            return False
        ffmpeg = next((w for w in self._watches if w.item.key == "ffmpeg"), None)
        if ffmpeg is not None and ffmpeg.startup_step is None and ffmpeg.last \
                and ffmpeg.last.seen == Seen.PROBLEM:  # no ffmpeg, no test (until it comes)
            self._runs.line(self._encoders_step, "Waits for ffmpeg")
            self._runs.end(self._encoders_step, failed=True, result="Waits for ffmpeg")
            self._encoders_step = None
            return False
        return True

    def check(self) -> None:
        """Bring the Runs up to date with how every Item is now (idempotent)."""
        for w in self._watches:
            now = w.item.observe()
            if w.last is None or (now.seen, now.line) != (w.last.seen, w.last.line):
                self._changed(w, now)
                w.last = now
        if self.startup is not None and all(w.startup_step is None for w in self._watches) \
                and not self._tests_waiting():
            failed = [w for w in self._watches if w.last and w.last.seen == Seen.PROBLEM]
            self._runs.finish_run(self.startup, failed=bool(failed) or self._tests_failed,
                                  detail=self._summary(failed))
            self.startup = None

    def _summary(self, failed: list[_Watch]) -> str:
        if failed:
            return "Trouble with " + ", ".join(w.item.step.split(" ", 1)[-1].removeprefix("the ")
                                               for w in failed)
        return "Tools ready, NAS connected"

    def _changed(self, w: _Watch, now: Observation) -> None:
        problem = now.seen == Seen.PROBLEM
        if w.startup_step is not None:
            if now.line:
                self._runs.line(w.startup_step, now.line, error=problem)
            if now.seen in (Seen.OK, Seen.PROBLEM):
                self._runs.end(w.startup_step, failed=problem, result=now.result)
                w.startup_step = None
                w.was_ok = not problem
            return
        if w.run is not None:
            assert w.run_step is not None
            if now.line:
                self._runs.line(w.run_step, now.line, error=problem)
            if now.seen == Seen.OK:
                self._runs.end(w.run_step, result=now.result)
                detail = now.result
                started = self._runs.get_run(w.run)
                if w.item.kind == RunKind.NAS and started is not None:
                    away = max(1, round((datetime.now() - started.started_at).total_seconds()
                                        / 60))
                    detail = f"{now.result} · away for {away} min"
                self._runs.finish_run(w.run, failed=False, title=w.item.fixed(w.was_ok),
                                      detail=detail)
                w.run = w.run_step = None
                w.was_ok = True
            elif problem:
                self._runs.set_result(w.run_step, now.result)
            return
        if now.seen in (Seen.PROBLEM, Seen.BUSY):
            w.run = self._runs.start_run(w.item.kind, w.item.trouble(w.was_ok), item=w.item.key,
                                         detail=now.result)
            if w.item.kind == RunKind.NAS and w.was_ok:
                hold = self._runs.begin(w.run, "hold", "Hold filing")
                self._runs.line(hold, "Filing waits until the NAS is back; Rips carry on to "
                                      "scratch")
                self._runs.end(hold, result=now.result)
            w.run_step = self._runs.begin(w.run, w.item.key, w.item.later_step or w.item.step)
            self._runs.line(w.run_step, now.line, error=problem)
            if problem:
                self._runs.set_result(w.run_step, now.result)
        elif now.seen == Seen.OK and w.last is not None and w.last.seen == Seen.PROBLEM:
            # Fine again with no Run open (it failed at startup): say so in a Run of its own.
            run = self._runs.start_run(w.item.kind, w.item.fixed(False), item=w.item.key,
                                       detail=now.result)
            step = self._runs.begin(run, w.item.key, w.item.later_step or w.item.step)
            self._runs.line(step, now.line)
            self._runs.end(step, result=now.result)
            self._runs.finish_run(run, failed=False)
            w.was_ok = True

    async def run(self) -> None:
        self.start()
        with self._bus.subscribe() as q:
            while True:
                self.check()
                try:
                    await asyncio.wait_for(q.get(), POLL_SECONDS)
                except TimeoutError:
                    pass
