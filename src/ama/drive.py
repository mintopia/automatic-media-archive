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

from ama.events import EventBus, Topic

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


def has_disc(state: DriveState) -> bool:
    return isinstance(state, DiscPresent | UnrecognisedDisc)


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

    def eject(self) -> None:
        """Open the tray. Raises OSError if the drive refuses."""
        ...

    def device(self) -> str | None:
        """The drive as ripping tools address it (e.g. "D:"), or None if there is none."""
        ...


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

    def device(self) -> str | None:
        return self._letter or self._find_letter()

    def eject(self) -> None:
        """Open the tray (IOCTL_STORAGE_EJECT_MEDIA). Raises OSError if it can't."""
        import ctypes
        from ctypes import wintypes

        letter = self.device()
        if letter is None:
            raise OSError("No optical drive found")
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateFileW.restype = wintypes.HANDLE
        GENERIC_READ, SHARE_RW, OPEN_EXISTING = 0x80000000, 0x3, 3
        h = k32.CreateFileW(f"\\\\.\\{letter}", GENERIC_READ, SHARE_RW, None,
                            OPEN_EXISTING, 0, None)
        if h in (None, wintypes.HANDLE(-1).value):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            IOCTL_STORAGE_EJECT_MEDIA = 0x2D4808
            returned = wintypes.DWORD()
            if not k32.DeviceIoControl(wintypes.HANDLE(h), IOCTL_STORAGE_EJECT_MEDIA, None, 0,
                                       None, 0, ctypes.byref(returned), None):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            k32.CloseHandle(wintypes.HANDLE(h))
        self._cache = None

    def probe(self) -> DriveState:
        import ctypes

        letter = self.device()
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


    def __init__(self, probe: DriveProbe, bus: EventBus, interval: float) -> None:
        self._probe = probe
        self._bus = bus
        self._interval = interval
        self.state: DriveState = DriveEmpty()
        # Counts Discs going in (no Disc -> a Disc). Rippers handle each insertion once
        # by this number, not by sampling `state`: a Disc swapped between two of their
        # looks is still a new Disc, even with the same label.
        self.insertion = 0

    async def poll_once(self) -> None:
        try:
            state = await asyncio.to_thread(self._probe.probe)
        except Exception as e:  # a flaky drive must never kill the poller
            log.exception("drive probe failed")
            state = DriveMissing(f"Couldn't read the drive: {e}")
        if state != self.state:
            log.info("drive: %s", state)
            if has_disc(state) and not has_disc(self.state):
                self.insertion += 1
            self.state = state
            self._bus.publish(Topic.DRIVE)

    def device(self) -> str | None:
        return self._probe.device()

    async def eject(self) -> None:
        """Eject the Disc, then re-read the drive so `state` reflects it at once.

        Raises OSError if the drive refuses (the drive is re-read either way).
        """
        try:
            await asyncio.to_thread(self._probe.eject)
        finally:
            await self.poll_once()

    async def run(self) -> None:
        while True:
            await self.poll_once()
            await asyncio.sleep(self._interval)
