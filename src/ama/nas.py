"""Keeping the NAS share connected (`net use`), and reporting when it isn't."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass

from ama.config import NasConfig
from ama.events import EventBus, Topic
from ama.proc import Runner, run

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class NasConnecting:
    pass


@dataclass(frozen=True)
class NasConnected:
    pass


@dataclass(frozen=True)
class NasUnreachable:
    unc: str
    detail: str


NasStatus = NasConnecting | NasConnected | NasUnreachable


class NasMonitor:
    """Connects the share at startup and re-checks it every `retry_seconds` (`check()` is
    idempotent)."""


    def __init__(
        self,
        cfg: NasConfig,
        bus: EventBus,
        runner: Runner = run,
        exists: Callable[[str], bool] = os.path.isdir,
    ) -> None:
        self.cfg = cfg
        self.bus = bus
        self._runner = runner
        self._exists = exists
        self.status: NasStatus = NasConnecting()

    def _connect(self) -> NasStatus:
        unc = self.cfg.unc
        if self._exists(unc):
            return NasConnected()
        args = ["net", "use", unc]
        if self.cfg.username:
            args += [self.cfg.password, f"/user:{self.cfg.username}"]
        args.append("/persistent:no")
        result = self._runner(args)
        if self._exists(unc):
            return NasConnected()
        lines = [ln.strip() for ln in result.output.splitlines() if ln.strip()]
        detail = lines[-1] if lines else f"net use exited with code {result.returncode}"
        if self.cfg.password:
            detail = detail.replace(self.cfg.password, "***")
        return NasUnreachable(unc, detail)

    async def check(self) -> None:
        try:
            status = await asyncio.to_thread(self._connect)
        except Exception as e:
            log.exception("NAS check failed")
            status = NasUnreachable(self.cfg.unc, str(e))
        if status != self.status:
            log.info("nas: %s", status)
            self.status = status
            self.bus.publish(Topic.NAS)

    async def run(self) -> None:
        while True:
            await self.check()
            await asyncio.sleep(self.cfg.retry_seconds)
