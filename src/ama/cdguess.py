"""A likely guess at what a CD is, shown while it rips, and the user's pick of release.

As soon as `cyanrip -I` gives the Disc ID, the CD Ripper asks MusicBrainz (through
the one rate-limited client) and the Cover Art Archive, and shows the most likely
release: album, artist, cover and track titles. The user can pick any other release
that fits from the rip card; the pick replaces the guess and is stored on the Job
(`cd_picks`), so later cards and Review offer it. Neither files anything by itself:
Identification and Review still decide what the Disc is.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

import httpx

from ama import cdreview
from ama.cdrip import CdRip, Track
from ama.covers import Covers
from ama.musicbrainz import Match, MusicBrainz, matches

if TYPE_CHECKING:
    from ama.db import Database

log = logging.getLogger(__name__)


def ranked(tracks: list[Track], candidates: Sequence[Match], mcn: str | None) -> list[Match]:
    """The releases that fit the Rip, likeliest first (barcode = MCN, then Official, then
    MusicBrainz's order)."""
    return sorted(cdreview.fitting(tracks, list(candidates)),
                  key=lambda m: (not (mcn and m.release.barcode == mcn),
                                 m.release.status != "Official"))


def likely(tracks: list[Track], candidates: Sequence[Match],
           mcn: str | None) -> tuple[Match | None, int]:
    """The likeliest release that fits the Rip, and how many fit."""
    fitting = ranked(tracks, candidates, mcn)
    return (fitting[0] if fitting else None), len(fitting)


def value(match: Match) -> str:
    """A release's disc as a form value: "<MusicBrainz release id>:<disc number>"."""
    return f"{match.release.id}:{match.disc_number}"


@dataclass(frozen=True)
class Guess:
    """The release the live rip card and Job page show: the likely one, or the user's pick."""

    match: Match
    candidates: tuple[Match, ...]  # every release that fits the Rip, likeliest first
    cover: str | None = None       # cached cover file name (see covers.py)
    picked: bool = False           # the user picked `match`

    @property
    def title(self) -> str:
        """The guessed release's title (the album's name)."""
        return self.match.release.title

    @property
    def releases(self) -> int:
        """How many releases fit the Rip ("1 of 3 versions")."""
        return len(self.candidates)

    def offered(self, release: str) -> Match | None:
        """The candidate whose `value` is `release`, if any."""
        return next((m for m in self.candidates if value(m) == release), None)

    def track_title(self, number: int) -> str | None:
        return next((t.title for t in self.match.tracks if t.number == number), None)


class Guesser:
    """Looks a ripping CD up early and puts the `Guess` on its live `CdRip`."""

    def __init__(self, mb: MusicBrainz, covers: Covers) -> None:
        self._mb = mb
        self._covers = covers

    async def follow(self, live: CdRip, mcn: str | None, publish: Callable[[], None],
                     retry_seconds: Callable[[], float]) -> None:
        """Guess until there is a guess or MusicBrainz doesn't know the Disc; MusicBrainz trouble
        just retries, quietly."""
        while True:
            try:
                response = await asyncio.to_thread(self._mb.lookup, live.mb_disc_id)
                break
            except (httpx.HTTPError, ValueError) as e:
                log.info("Early Identification from MusicBrainz failed (%s); trying again later",
                         type(e).__name__)
                await asyncio.sleep(retry_seconds())
        if response is None:
            return
        fitting = ranked(live.tracks, matches(response, live.mb_disc_id), mcn)
        if not fitting:
            return
        match = fitting[0]
        live.guess = Guess(match, tuple(fitting))
        publish()
        cover = await self.cover(match)
        if cover and live.guess.match == match:  # not replaced by a pick meanwhile
            live.guess = replace(live.guess, cover=cover)
            publish()

    async def pick(self, live: CdRip, release: str) -> CdPick | None:
        """Show `release` ("<release id>:<disc number>") on the live rip card instead of the
        guess, with its cover; None if it isn't one of the releases that fit."""
        match = live.guess.offered(release) if live.guess else None
        if match is None:
            return None
        cover = await self.cover(match)
        live.guess = Guess(match, live.guess.candidates, cover, picked=True)
        return CdPick.of(match, cover)

    async def cover(self, match: Match) -> str | None:
        """The release's cached front cover, fetched if need be; None if it has none or the
        Cover Art Archive can't be reached."""
        try:
            return await asyncio.to_thread(self._covers.release, match.release)
        except (httpx.HTTPError, OSError) as e:
            log.info("Cover art fetch failed (%s)", type(e).__name__)
            return None


@dataclass(frozen=True)
class CdPick:
    """The release the user picked for a CD Job while it ripped."""

    release_id: str
    disc_number: int
    album: str
    artist: str
    cover: str | None = None  # cached cover file name (see covers.py)

    @classmethod
    def of(cls, match: Match, cover: str | None) -> CdPick:
        r = match.release
        return cls(r.id, match.disc_number, r.title, r.artist, cover)

    @property
    def value(self) -> str:
        return f"{self.release_id}:{self.disc_number}"

    @property
    def name(self) -> str:
        return f"{self.album} — {self.artist}"


class CdPicks:
    """The `cd_picks` table: a CD Job's picked release; a later pick replaces it."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def save(self, job_id: int, pick: CdPick) -> None:
        self._db.execute(
            "INSERT INTO cd_picks (job_id, release_id, disc_number, album, artist, cover) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(job_id) DO UPDATE SET "
            "release_id = excluded.release_id, disc_number = excluded.disc_number, "
            "album = excluded.album, artist = excluded.artist, cover = excluded.cover",
            (job_id, pick.release_id, pick.disc_number, pick.album, pick.artist, pick.cover))

    def get(self, job_id: int) -> CdPick | None:
        row = self._db.execute(
            "SELECT release_id, disc_number, album, artist, cover FROM cd_picks "
            "WHERE job_id = ?", (job_id,)).fetchone()
        return CdPick(*row) if row else None
