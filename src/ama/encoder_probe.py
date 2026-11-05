"""Which encoders work on this PC (ADR 0010): a short test encode with each.

`EncoderProbe` (`services.encoders`, a background task) test-encodes every encoder in
`encode.ENCODERS` once ffmpeg is ready, then again whenever `request()` is called
(the Encode settings were saved, or "Test encoders again"). Settings offers only the
encoders whose last test worked; `problem()` is the configured encoder failing its
test, which the tools banner and the Encode settings warn about. Results are memory
only: every start tests afresh.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from ama import encode
from ama.config import EncodeConfig, EncoderName
from ama.events import EventBus, Topic
from ama.proc import Streamer
from ama.tools import ToolLookup, ToolUnavailable

log = logging.getLogger(__name__)


class ProbeLog(Protocol):
    """Where a test run's lines go in Logs (`app_events.AppEvents` is one)."""

    def begin(self) -> int: ...
    def line(self, step: int, text: str, error: bool = False) -> None: ...
    def end(self, step: int, failed: bool, result: str) -> None: ...


@dataclass(frozen=True)
class ProbeUntested:
    """Not tested yet (ffmpeg isn't ready, or the first test is running)."""


@dataclass(frozen=True)
class ProbeWorks:
    at: datetime


@dataclass(frozen=True)
class ProbeFailed:
    at: datetime
    detail: str  # ffmpeg's last words


ProbeState = ProbeUntested | ProbeWorks | ProbeFailed


@dataclass(frozen=True)
class EncoderProblem:
    """The configured encoder failed its last test encode."""

    encoder: EncoderName
    label: str
    at: datetime
    detail: str
    stopped: bool  # it worked earlier in this run ("stopped working")


class EncoderProbe:
    def __init__(self, bus: EventBus, tool: ToolLookup, streamer: Streamer,
                 config: Callable[[], EncodeConfig], clock: Callable[[], datetime] = datetime.now,
                 retry_seconds: float = 5.0) -> None:
        self._bus = bus
        self._tool = tool
        self._stream = streamer
        self._config = config  # the running [encode] settings
        self._clock = clock
        self.retry_seconds = retry_seconds
        self.states: dict[EncoderName, ProbeState] = {e: ProbeUntested() for e in encode.ENCODERS}
        self._worked: set[EncoderName] = set()
        self._again = asyncio.Event()
        self._lock = asyncio.Lock()
        # Logs: each test run is a Step (app_events.EncoderTests); None keeps no record.
        self.log: ProbeLog | None = None

    def working(self) -> list[EncoderName]:
        return [e for e, s in self.states.items() if isinstance(s, ProbeWorks)]

    def problem(self) -> EncoderProblem | None:
        name = self._config().encoder
        state = self.states[name]
        if not isinstance(state, ProbeFailed):
            return None
        return EncoderProblem(name, encode.ENCODERS[name].label, state.at, state.detail,
                              stopped=name in self._worked)

    def request(self) -> None:
        """Test again soon (idempotent: several requests make one test run)."""
        self._again.set()

    async def run(self) -> None:
        while True:
            try:
                await self.probe_all()
            except ToolUnavailable:
                await asyncio.sleep(self.retry_seconds)  # ffmpeg is still on its way
                continue
            await self._again.wait()
            self._again.clear()

    async def probe_all(self) -> None:
        """Test every encoder now. Raises ToolUnavailable while ffmpeg isn't ready."""
        ffmpeg = self._tool("ffmpeg")
        async with self._lock:
            speed = self._config().speed
            at = self._clock()  # one test run, one time ("the test at 20:14")
            step = self.log.begin() if self.log else None

            def say(text: str, error: bool = False) -> None:
                if self.log and step is not None:
                    self.log.line(step, text, error)

            say("Test encode: 5 s of a 1080p test pattern with each encoder")
            for name in encode.ENCODERS:
                lines: list[str] = []
                try:
                    code = await asyncio.to_thread(
                        self._stream, encode.probe_args(ffmpeg, name, speed), lines.append)
                except OSError as e:
                    code, lines = -1, [f"ffmpeg couldn't be started ({e.strerror or e})"]
                if code == 0:
                    self.states[name] = ProbeWorks(at)
                    self._worked.add(name)
                    log.info("encoder test: %s works", name)
                    say(f"{name} works · {encode.ENCODERS[name].label}")
                else:
                    detail = next((ln.strip() for ln in lines if ln.strip()),
                                  f"ffmpeg exit code {code}")
                    self.states[name] = ProbeFailed(at, detail)
                    log.info("encoder test: %s doesn't work: %s", name, " | ".join(lines[-5:]))
                    say(f"{name} doesn't work · {encode.ENCODERS[name].label}")
                    for ln in lines[-5:]:
                        say(ln, error=True)
            configured = self._config().encoder
            works = isinstance(self.states[configured], ProbeWorks)
            verdict = "works" if works else "doesn't work"
            say(f"Configured encoder: {encode.ENCODERS[configured].label} · {verdict}",
                error=not works)
            if self.log and step is not None:
                n = len(self.working())
                self.log.end(step, failed=not works,
                             result=f"{n} of {len(encode.ENCODERS)} work on this PC")
        self._bus.publish(Topic.TOOLS)
