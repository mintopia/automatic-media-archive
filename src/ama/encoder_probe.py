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

from ama import encode
from ama.config import EncodeConfig, EncoderName
from ama.events import EventBus, Topic
from ama.proc import Streamer
from ama.tools import ToolLookup, ToolUnavailable

log = logging.getLogger(__name__)


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
                else:
                    detail = next((ln.strip() for ln in lines if ln.strip()),
                                  f"ffmpeg exit code {code}")
                    self.states[name] = ProbeFailed(at, detail)
                    log.info("encoder test: %s doesn't work: %s", name, " | ".join(lines[-5:]))
        self._bus.publish(Topic.TOOLS)
