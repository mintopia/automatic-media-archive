"""The optical drive: what is in it, and watching it for changes.

`DriveState` is the single source of truth for "what is in the drive". It is
produced by a `DriveProbe` (the OS boundary; faked in tests) and watched by
`DriveMonitor`, which publishes a `drive` event on the bus whenever it changes.
"""

from __future__ import annotations

import asyncio
import logging
import string
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from ama.events import EventBus

log = logging.getLogger(__name__)


class DiscType(StrEnum):
    CD = "CD"
    DVD = "DVD"
    BD = "BD"
    UHD = "UHD"

    @property
    def long_name(self) -> str:
        return _LONG_NAMES[self]


_LONG_NAMES = {
    DiscType.CD: "Audio CD",
    DiscType.DVD: "DVD",
    DiscType.BD: "Blu-ray",
    DiscType.UHD: "UHD Blu-ray",
}


@dataclass(frozen=True)
class DriveEmpty:
    pass


@dataclass(frozen=True)
class DiscPresent:
    disc_type: DiscType
    label: str


@dataclass(frozen=True)
class UnrecognisedDisc:
    """Media is loaded but it is none of the Disc Types (e.g. a data disc)."""

    label: str


@dataclass(frozen=True)
class DriveMissing:
    """No optical drive could be found or read."""

    reason: str


DriveState = DriveEmpty | DiscPresent | UnrecognisedDisc | DriveMissing


def classify_root(root: Path) -> DiscType | None:
    """Work out the Disc Type from the filesystem Windows exposes for a Disc."""
    try:
        names = {p.name.upper(): p for p in root.iterdir()}
    except OSError:
        return None
    if any(n.endswith(".CDA") for n in names):
        return DiscType.CD
    if "VIDEO_TS" in names:
        return DiscType.DVD
    if "BDMV" in names:
        # index.bdmv starts "INDX" + version; UHD Blu-ray uses version "0300".
        try:
            with open(names["BDMV"] / "index.bdmv", "rb") as f:
                header = f.read(8)
        except OSError:
            return DiscType.BD
        return DiscType.UHD if header[4:8] == b"0300" else DiscType.BD
    return None


class DriveProbe(Protocol):
    def probe(self) -> DriveState: ...


class WindowsDriveProbe:
    """Reads the optical drive through Win32 (GetVolumeInformationW) and its root.

    `letter` is e.g. "D:"; None picks the first drive Windows reports as CD-ROM.
    Classification is cached per volume (serial number + label) so a loaded
    Disc is only listed once, not every poll.
    """

    def __init__(self, letter: str | None = None) -> None:
        import ctypes

        self._k32 = ctypes.windll.kernel32
        # Never pop up "There is no disk in the drive" dialogs.
        SEM_FAILCRITICALERRORS = 0x0001
        self._k32.SetErrorMode(SEM_FAILCRITICALERRORS)
        self._letter = letter.rstrip(":\\").upper() + ":" if letter else None
        self._cache: tuple[tuple[int, str], DriveState] | None = None

    def _find_letter(self) -> str | None:
        DRIVE_CDROM = 5
        for c in string.ascii_uppercase:
            if self._k32.GetDriveTypeW(f"{c}:\\") == DRIVE_CDROM:
                return f"{c}:"
        return None

    def probe(self) -> DriveState:
        import ctypes

        letter = self._letter or self._find_letter()
        if letter is None:
            return DriveMissing("No optical drive found")
        root = f"{letter}\\"
        label = ctypes.create_unicode_buffer(261)
        fs = ctypes.create_unicode_buffer(261)
        serial = ctypes.c_uint32()
        ok = self._k32.GetVolumeInformationW(
            root, label, 261, ctypes.byref(serial), None, None, fs, 261
        )
        if not ok:
            err = ctypes.GetLastError()
            ERROR_NOT_READY, ERROR_UNRECOGNIZED_MEDIA = 21, 1785
            if err == ERROR_NOT_READY:
                self._cache = None
                return DriveEmpty()
            if err == ERROR_UNRECOGNIZED_MEDIA:
                return UnrecognisedDisc(label="")
            if self._k32.GetDriveTypeW(root) != 5:
                return DriveMissing(f"{letter} is not an optical drive")
            return DriveEmpty()
        key = (serial.value, label.value)
        if self._cache and self._cache[0] == key:
            return self._cache[1]
        disc_type = classify_root(Path(root))
        state: DriveState = (
            DiscPresent(disc_type, label.value) if disc_type else UnrecognisedDisc(label.value)
        )
        self._cache = (key, state)
        return state


def default_probe(letter: str | None) -> DriveProbe:
    if sys.platform != "win32":
        raise RuntimeError("Drive detection is only implemented for Windows")
    return WindowsDriveProbe(letter)


class DriveMonitor:
    """Polls the probe and publishes `drive` on the bus when the state changes."""

    TOPIC = "drive"

    def __init__(self, probe: DriveProbe, bus: EventBus, interval: float) -> None:
        self._probe = probe
        self._bus = bus
        self._interval = interval
        self.state: DriveState = DriveEmpty()

    async def poll_once(self) -> None:
        try:
            state = await asyncio.to_thread(self._probe.probe)
        except Exception as e:  # a flaky drive must never kill the poller
            log.exception("drive probe failed")
            state = DriveMissing(f"Couldn't read the drive: {e}")
        if state != self.state:
            log.info("drive: %s", state)
            self.state = state
            self._bus.publish(self.TOPIC)

    async def run(self) -> None:
        while True:
            await self.poll_once()
            await asyncio.sleep(self._interval)
