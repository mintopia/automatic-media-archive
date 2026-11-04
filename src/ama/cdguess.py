"""A likely guess at what a CD is, shown while it rips.

As soon as `cyanrip -I` gives the Disc ID, the CD Ripper asks MusicBrainz (through
the one rate-limited client) and the Cover Art Archive, and shows the most likely
release: album, artist, cover and track titles. It is only for show. Identification
and Review still decide what the Disc is, and the guess never files anything.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

import httpx

from ama import cdreview
from ama.cdrip import CdRip, Track
from ama.covers import Covers
from ama.musicbrainz import Match, MusicBrainz, matches

log = logging.getLogger(__name__)


def likely(tracks: list[Track], candidates: Sequence[Match],
           mcn: str | None) -> tuple[Match | None, int]:
    """The most likely of the releases that fit the Rip, and how many fit.

    Likeliest: the release whose barcode is the Disc's MCN, then an Official one, then
    MusicBrainz's order.
    """
    fitting = cdreview.fitting(tracks, list(candidates))
    if not fitting:
        return None, 0
    best = min(fitting, key=lambda m: (not (mcn and m.release.barcode == mcn),
                                       m.release.status != "Official"))
    return best, len(fitting)


@dataclass(frozen=True)
class Guess:
    """The likely release, as the live rip card and Disc page show it."""

    match: Match
    releases: int            # how many releases fit the Rip ("1 of 3 releases")
    cover: str | None = None  # cached cover file name (see covers.py)

    def track_title(self, number: int) -> str | None:
        return next((t.title for t in self.match.tracks if t.number == number), None)


class Guesser:
    """Looks a ripping CD up early and puts the `Guess` on its live `CdRip`."""

    def __init__(self, mb: MusicBrainz, covers: Covers) -> None:
        self._mb = mb
        self._covers = covers

    async def follow(self, live: CdRip, mcn: str | None, publish: Callable[[], None],
                     retry_seconds: Callable[[], float]) -> None:
        """Guess until there is a guess, or MusicBrainz says it doesn't know the Disc.

        MusicBrainz trouble (offline, 503) is quiet: the card keeps showing the Disc ID
        and track count, and this asks again after `retry_seconds()`. Cancelled when the
        Rip ends.
        """
        while True:
            try:
                response = await asyncio.to_thread(self._mb.lookup, live.mb_disc_id)
                break
            except (httpx.HTTPError, ValueError) as e:
                log.info("Early MusicBrainz lookup failed (%s); trying again later",
                         type(e).__name__)
                await asyncio.sleep(retry_seconds())
        if response is None:
            return
        match, count = likely(live.tracks, matches(response, live.mb_disc_id), mcn)
        if match is None:
            return
        live.guess = Guess(match, count)
        publish()
        try:
            cover = await asyncio.to_thread(self._covers.release, match.release)
        except (httpx.HTTPError, OSError) as e:
            log.info("Early cover art fetch failed (%s)", type(e).__name__)
            return
        if cover:
            live.guess = replace(live.guess, cover=cover)
            publish()
