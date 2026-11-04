"""Repeat-Disc warning (#16): a Disc that's already in the Archive isn't ripped again
until the user chooses.

Every Rip remembers its Disc's fingerprint (`remember`). On insert, before ripping,
each ripper asks `RepeatGuard.admit(disc_type, fingerprint)`: a Disc that matches a
filed one pauses there (`pending`, shown on the Now page) until the user picks
"Eject, don't archive" (`Choice.SKIP`: eject, no Rip) or "Archive again"
(`Choice.AGAIN`: rip as normal), or takes the Disc out. Fingerprints are per Disc:
CD = MusicBrainz Disc ID; video = hash of the Disc's file structure, so a BD and a
UHD (or two editions) of the same film are different Discs.
"""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from ama.db import Database
from ama.discs import DiscRecord, DiscStore
from ama.drive import DiscType, DriveMonitor
from ama.events import EventBus

log = logging.getLogger(__name__)

# The folders that make up a video Disc's structure, per Disc Type.
_STRUCTURE = {DiscType.DVD: "VIDEO_TS", DiscType.BD: "BDMV", DiscType.UHD: "BDMV"}


def cd_fingerprint(disc_id: str | None) -> str | None:
    return f"{DiscType.CD}:{disc_id}" if disc_id else None


def video_fingerprint(root: Path | None, disc_type: DiscType) -> str | None:
    """Hash of every file's path and size under VIDEO_TS / BDMV; None if unreadable."""
    folder = _STRUCTURE.get(disc_type)
    if root is None or folder is None:
        return None
    base = root / folder
    entries: list[str] = []
    try:
        if not base.is_dir():
            return None
        for dirpath, _dirs, files in os.walk(base, onerror=_raise):
            for name in files:
                p = Path(dirpath) / name
                rel = p.relative_to(root).as_posix().upper()
                entries.append(f"{rel}\t{p.stat().st_size}")
    except OSError as e:
        log.warning("couldn't read the Disc's structure: %s", e)
        return None
    digest = hashlib.sha256("\n".join(sorted(entries)).encode()).hexdigest()
    return f"{disc_type}:{digest}"


def _raise(e: OSError) -> None:
    raise e


class Choice(StrEnum):
    SKIP = "skip"    # eject, don't archive
    AGAIN = "again"  # archive it again


_OTHER_FORMAT = {DiscType.BD: "UHD Blu-ray", DiscType.UHD: "Blu-ray", DiscType.DVD: "Blu-ray"}


@dataclass(frozen=True)
class RepeatDisc:
    """A Disc in the drive that matches one already filed, waiting for the user's choice."""

    disc_type: DiscType
    previous: DiscRecord  # the filed Disc it matches
    folder: str           # where that was filed, relative to the Archive root

    @property
    def name(self) -> str:
        return self.previous.title or self.previous.name

    @property
    def note(self) -> str:
        other = _OTHER_FORMAT.get(self.disc_type)
        if other is None:
            return "Other editions of this album are different Discs and won't trigger this."
        return f"The {other} of {self.name} is a different Disc and won't trigger this."


class RepeatGuard:
    def __init__(self, db: Database, discs: DiscStore, drive: DriveMonitor, bus: EventBus,
                 archive_root: Path) -> None:
        self._db = db
        self._discs = discs
        self._drive = drive
        self._bus = bus
        self._archive_root = archive_root
        self.pending: RepeatDisc | None = None
        self._choice: Choice | None = None

    def remember(self, disc_id: int, fingerprint: str | None) -> None:
        if fingerprint:
            self._db.execute("INSERT OR REPLACE INTO disc_fingerprints (disc_id, fingerprint) "
                             "VALUES (?, ?)", (disc_id, fingerprint))

    def known(self, fingerprint: str) -> DiscRecord | None:
        """The most recently filed Disc with this fingerprint."""
        row = self._db.execute(
            "SELECT d.id FROM disc_fingerprints f JOIN discs d ON d.id = f.disc_id "
            "WHERE f.fingerprint = ? AND d.status = 'filed' "
            "ORDER BY d.filed_at DESC, d.id DESC LIMIT 1", (fingerprint,)).fetchone()
        return self._discs.get(row[0]) if row else None

    async def admit(self, disc_type: DiscType, fingerprint: str | None) -> bool:
        """True = rip this Disc. A filed Disc waits here for the user's choice."""
        previous = self.known(fingerprint) if fingerprint else None
        if previous is None:
            return True
        inserted = self._drive.state
        self._choice = None
        self.pending = RepeatDisc(disc_type, previous, self._folder(previous))
        log.info("Repeat Disc: matches Disc %s (%s)", previous.id, self.pending.name)
        self._publish()
        try:
            with self._bus.subscribe() as q:
                while self._choice is None and self._drive.state == inserted:
                    await q.get()
        finally:
            self.pending = None
        choice, self._choice = self._choice, None
        if choice is Choice.SKIP:
            try:
                await self._drive.eject()
            except OSError as e:
                log.warning("Couldn't eject the Disc: %s", e)
        self._publish()
        return choice is Choice.AGAIN

    def choose(self, choice: Choice) -> None:
        """The user's answer; ignored if nothing is waiting (e.g. the Disc was taken out)."""
        if self.pending is not None:
            self._choice = choice
            self._publish()

    def _folder(self, rec: DiscRecord) -> str:
        if rec.archive_dir is None:
            return ""
        try:
            return rec.archive_dir.relative_to(self._archive_root).as_posix()
        except ValueError:
            return str(rec.archive_dir)

    def _publish(self) -> None:
        self._bus.publish(DriveMonitor.TOPIC)  # the drive card
        self._bus.publish("rip")               # the Ripping bin
