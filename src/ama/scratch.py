"""Scratch space: how full it is, and the gate that refuses a Disc it can't hold (ADR-0005).

Every Rip lands on local scratch and stays there through Identification, Review
and Encode, so a Review or Encode backlog fills it. Before a Rip starts, the
ripper asks `ScratchGate.refuses(disc_type, label)`: if free space is below
that Disc Type's configured threshold (`[scratch]` in ama.toml) the Disc is
ejected unripped, no Disc record is made, and `refused` says why for the UI
until the next Disc is let in.
"""

from __future__ import annotations

import logging
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from ama.config import ScratchConfig
from ama.drive import DiscType, DriveMonitor
from ama.events import EventBus

log = logging.getLogger(__name__)

GB = 1000**3
TOPIC = "scratch"


class DiskUsage(NamedTuple):
    total: int
    used: int
    free: int


DiskUsageFn = Callable[[Path], DiskUsage]


@dataclass(frozen=True)
class ScratchUsage:
    used: int
    total: int
    free: int
    full: bool  # some Disc Type would be refused now

    @property
    def used_gb(self) -> int:
        return round(self.used / GB)

    @property
    def total_gb(self) -> int:
        return round(self.total / GB)

    @property
    def pct(self) -> float:
        return round(100 * self.used / self.total, 1) if self.total else 0


_ARTICLE = {DiscType.CD: "an", DiscType.DVD: "a", DiscType.BD: "a", DiscType.UHD: "a"}


@dataclass(frozen=True)
class Refusal:
    """A Disc ejected unripped because scratch couldn't hold it."""

    disc_type: DiscType
    label: str
    usage: ScratchUsage
    need_gb: int

    @property
    def name(self) -> str:
        return self.label or self.disc_type.long_name

    @property
    def needs(self) -> str:
        """e.g. "a Blu-ray needs up to 50 GB"."""
        return f"{_ARTICLE[self.disc_type]} {self.disc_type.long_name} needs up to {self.need_gb} GB"


class ScratchGate:
    def __init__(self, cfg: ScratchConfig, root: Path, drive: DriveMonitor, bus: EventBus,
                 disk_usage: DiskUsageFn = shutil.disk_usage) -> None:  # type: ignore[assignment]
        self._cfg = cfg
        self._root = root
        self._drive = drive
        self._bus = bus
        self._disk_usage = disk_usage
        self.refused: Refusal | None = None

    def need_gb(self, disc_type: DiscType) -> int:
        return {DiscType.CD: self._cfg.cd, DiscType.DVD: self._cfg.dvd,
                DiscType.BD: self._cfg.bd, DiscType.UHD: self._cfg.uhd}[disc_type]

    def usage(self) -> ScratchUsage | None:
        try:
            du = self._disk_usage(self._root)
        except OSError:
            return None
        biggest = max(self.need_gb(t) for t in DiscType)
        return ScratchUsage(du.used, du.total, du.free, full=du.free < biggest * GB)

    async def refuses(self, disc_type: DiscType, label: str) -> bool:
        """True = scratch can't hold this Disc: it has been ejected and must not be ripped."""
        usage = self.usage()
        need = self.need_gb(disc_type)
        if usage is None or usage.free >= need * GB:
            if self.refused is not None:
                self.refused = None
                self._publish()
            return False
        self.refused = Refusal(disc_type, label, usage, need)
        log.info("Scratch full (%d GB free): ejecting %s “%s” unripped",
                 usage.free // GB, disc_type.long_name, label)
        try:
            await self._drive.eject()
        except OSError as e:
            log.warning("Couldn't eject the Disc: %s", e)
        self._publish()
        return True

    def _publish(self) -> None:
        self._bus.publish(TOPIC)
        self._bus.publish(DriveMonitor.TOPIC)
