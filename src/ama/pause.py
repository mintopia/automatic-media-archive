"""Paused (GLOSSARY.md): AMA ignores newly inserted Discs until resumed.

Only the rippers ask; a Rip under way, Encodes, archiving and Review never look at it.
A Disc that went in while paused is not marked handled, so resuming picks it up.
Kept in SQLite (not `ama.toml`), so it survives a restart.
"""

from __future__ import annotations

from ama.db import Database
from ama.events import EventBus, Topic

KEY = "paused"


class Pause:
    def __init__(self, db: Database, bus: EventBus) -> None:
        self._db = db
        self._bus = bus
        self.paused = db.get_value(KEY) == "1"

    def set(self, paused: bool) -> None:
        if paused == self.paused:
            return
        self._db.set_value(KEY, "1" if paused else "0")
        self.paused = paused
        # Wakes the Video ripper too: it waits on the bus, so resuming reconsiders the drive.
        self._bus.publish(Topic.PAUSE)
