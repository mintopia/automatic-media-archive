"""Repeat-Disc warning: a Disc already in the Archive, or ripped and still on its way
there, isn't ripped again until the user chooses.

Fingerprints are per Disc: CD = MusicBrainz Disc ID; video = hash of the Disc's file
structure, so a BD and a UHD (or two editions) of the same film are different Discs.
"""

from __future__ import annotations

import hashlib
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from ama.db import Database
from ama.jobs import JobRecord, JobStatus, JobStore
from ama.drive import DiscType, DriveMonitor
from ama.events import EventBus, Topic

log = logging.getLogger(__name__)

# The folders that make up a video Disc's structure, per Disc Type.
_STRUCTURE = {DiscType.DVD: "VIDEO_TS", DiscType.BD: "BDMV", DiscType.UHD: "BDMV"}


def cd_fingerprint(mb_disc_id: str | None) -> str | None:
    return f"{DiscType.CD}:{mb_disc_id}" if mb_disc_id else None


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


KNOWN = (JobStatus.ARCHIVED, JobStatus.REVIEW, JobStatus.RIPPED)  # archived, or on the way
_OTHER_FORMAT = {DiscType.BD: "UHD Blu-ray", DiscType.UHD: "Blu-ray", DiscType.DVD: "Blu-ray"}


@dataclass(frozen=True)
class RepeatDisc:
    """A Disc in the drive that matches a known one, waiting for the user's choice."""

    disc_type: DiscType
    previous: JobRecord  # the known Disc it matches
    folder: str           # where that was archived, relative to the Archive root ("" if not yet)

    @property
    def name(self) -> str:
        return self.previous.title or self.previous.name

    @property
    def archived(self) -> bool:
        return self.previous.status == JobStatus.ARCHIVED

    @property
    def waiting(self) -> str:
        """Where the known Disc is on its way to the Archive ("" once archived)."""
        if self.previous.status == JobStatus.REVIEW:
            return "Already ripped, waiting for Review"
        return "" if self.archived else "Already ripped, waiting to be archived"

    @property
    def note(self) -> str:
        other = _OTHER_FORMAT.get(self.disc_type)
        if other is None:
            return "Other editions of this album are different Discs and won't trigger this."
        return f"The {other} of {self.name} is a different Disc and won't trigger this."


class RepeatGuard:
    def __init__(self, db: Database, jobs: JobStore, drive: DriveMonitor, bus: EventBus,
                 shown: Callable[[Path], str]) -> None:
        self._db = db
        self._jobs = jobs
        self._drive = drive
        self._bus = bus
        self._shown = shown  # `Archive.shown`
        self.pending: RepeatDisc | None = None
        self._choice: Choice | None = None

    def remember(self, job_id: int, fingerprint: str | None) -> None:
        if fingerprint:
            self._db.execute("INSERT OR REPLACE INTO disc_fingerprints (job_id, fingerprint) "
                             "VALUES (?, ?)", (job_id, fingerprint))

    def known(self, fingerprint: str) -> JobRecord | None:
        """The latest Disc with this fingerprint that is archived or on its way there."""
        row = self._db.execute(
            "SELECT d.id FROM disc_fingerprints f JOIN jobs d ON d.id = f.job_id "
            "WHERE f.fingerprint = ? AND d.status IN (?, ?, ?) "
            "ORDER BY d.id DESC LIMIT 1",
            (fingerprint, *KNOWN)).fetchone()
        return self._jobs.get(row[0]) if row else None

    async def admit(self, disc_type: DiscType, fingerprint: str | None) -> bool:
        """True = rip this Disc. A known Disc waits here for the user's choice."""
        previous = self.known(fingerprint) if fingerprint else None
        if previous is None:
            return True
        inserted = self._drive.state, self._drive.insertion
        self._choice = None
        self.pending = RepeatDisc(disc_type, previous, self._folder(previous))
        log.info("Repeat Disc: matches Job %s (%s)", previous.id, self.pending.name)
        self._publish()
        try:
            with self._bus.subscribe() as q:
                while self._choice is None and \
                        (self._drive.state, self._drive.insertion) == inserted:
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

    def _folder(self, rec: JobRecord) -> str:
        return "" if rec.archive_dir is None else self._shown(rec.archive_dir)

    def _publish(self) -> None:
        self._bus.publish(Topic.DRIVE)  # the drive card
        self._bus.publish(Topic.RIP)    # the Ripping bin
