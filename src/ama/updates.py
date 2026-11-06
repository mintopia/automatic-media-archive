"""Update available (ADR 0017): is there a newer AMA Release on GitHub than this one?

Only `vX.Y.Z` Releases count: never `cyanrip-*` builds (ADR 0015), pre-releases or drafts.
GitHub is asked at most once a day, counted across restarts (the last check is kept in
SQLite), and a failed check waits a day too. Failures are silent: no banner, no Run.
AMA never updates itself; the notice links to the Release, whose installer upgrades in place.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import version
from typing import NamedTuple

import httpx

from ama.db import Database
from ama.events import EventBus, Topic

log = logging.getLogger(__name__)

RELEASES_URL = "https://api.github.com/repos/mintopia/automatic-media-archive/releases"
KEY = "update_check"  # kv: {"checked_at": epoch seconds, "release": {"tag", "url"} | null}
DAY = 24 * 3600.0

_NUMBERS = re.compile(r"(\d+)\.(\d+)\.(\d+)")


class Version(NamedTuple):
    """X.Y.Z, compared as numbers."""

    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, text: str, *, whole: bool = False) -> Version | None:
        """`X.Y.Z` at the start of `text` (an installed "1.2.3.dev0" is 1.2.3), or the
        whole of it with `whole`; None if it isn't there."""
        m = (_NUMBERS.fullmatch if whole else _NUMBERS.match)(text)
        return cls(int(m[1]), int(m[2]), int(m[3])) if m else None

    @classmethod
    def of_tag(cls, tag: str) -> Version | None:
        """An AMA Release's tag is exactly `vX.Y.Z`; None for any other tag."""
        return cls.parse(tag[1:], whole=True) if tag.startswith("v") else None

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


@dataclass(frozen=True)
class Release:
    version: Version  # parsed from the tag, once
    url: str  # the Release's page on GitHub

    @property
    def tag(self) -> str:
        return f"v{self.version}"


def newest(releases: object) -> Release | None:
    """The newest AMA Release in GitHub's list-releases answer, or None.
    Raises ValueError when the answer isn't that list."""
    if not isinstance(releases, list):
        raise ValueError("expected a list of releases")
    found: list[Release] = []
    for r in releases:
        if not isinstance(r, dict) or r.get("draft") or r.get("prerelease"):
            continue
        tag, url = r.get("tag_name"), r.get("html_url")
        if isinstance(tag, str) and isinstance(url, str) and (v := Version.of_tag(tag)):
            found.append(Release(v, url))
    return max(found, key=lambda r: r.version, default=None)


class UpdateCheck:
    def __init__(self, http: httpx.Client, db: Database, bus: EventBus,
                 running: str | None = None, now: Callable[[], float] = time.time) -> None:
        self._http = http
        self._db = db
        self._bus = bus
        self._running = Version.parse(running if running is not None else version("ama"))
        self._now = now
        self._checked_at, self._latest = self._load()

    @property
    def available(self) -> Release | None:
        """The Release to show as "Update available", if it's newer than this AMA."""
        latest = self._latest
        if latest is None or self._running is None:
            return None
        return latest if latest.version > self._running else None

    def due_in(self) -> float:
        """Seconds until the next check may ask GitHub."""
        if self._checked_at is None:
            return 0.0
        return max(0.0, self._checked_at + DAY - self._now())

    def check(self) -> bool:
        """Ask GitHub, unless it was asked less than a day ago. True if `available` changed."""
        if self.due_in() > 0:
            return False
        before = self.available
        self._checked_at = self._now()
        try:
            resp = self._http.get(RELEASES_URL, params={"per_page": 100},
                                  headers={"Accept": "application/vnd.github+json"})
            resp.raise_for_status()
            self._latest = newest(resp.json())
        except (httpx.HTTPError, ValueError) as e:  # silent: try again tomorrow
            log.info("update check: couldn't ask GitHub: %s", e)
        self._save()
        return self.available != before

    async def run(self) -> None:
        while True:
            try:
                if await asyncio.to_thread(self.check):
                    self._bus.publish(Topic.UPDATE)
            except Exception:  # never kill the loop, never show the user
                log.exception("update check failed")
            await asyncio.sleep(max(self.due_in(), 60.0))

    def _load(self) -> tuple[float | None, Release | None]:
        try:
            saved = json.loads(self._db.get_value(KEY) or "null")
            checked_at = float(saved["checked_at"])
            rel = saved.get("release")
            v = Version.of_tag(rel["tag"]) if rel else None
            return checked_at, Release(v, rel["url"]) if v else None
        except (ValueError, TypeError, KeyError):
            return None, None

    def _save(self) -> None:
        rel = self._latest
        self._db.set_value(KEY, json.dumps({
            "checked_at": self._checked_at,
            "release": {"tag": rel.tag, "url": rel.url} if rel else None}))
