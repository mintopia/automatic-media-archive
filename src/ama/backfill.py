"""One-off fill-in of History details for Discs filed before they were kept (migration 0012).

Runs once at every start and only touches filed Discs with no `media_info` row, so it
converges and is a no-op once done. A CD's release comes from its Disc log (the
"MusicBrainz release <id>" line written when it was identified) and its Disc ID from
its fingerprint; a film or series from the `movies` / `tv_titles` rows. Anything that
can't be fetched now is left for the next start.
"""

from __future__ import annotations

import asyncio
import logging
import re

import httpx

from ama.covers import Covers
from ama.db import Database
from ama.discs import DiscRecord, DiscStatus, DiscStore
from ama.drive import DiscType
from ama.media import Album, MediaStore, screen
from ama.moviearchive import Movies
from ama.musicbrainz import MusicBrainz, matches
from ama.tmdb import Tmdb
from ama.tvarchive import TvTitles

log = logging.getLogger(__name__)

_RELEASE = re.compile(r"MusicBrainz release ([0-9a-f-]{36})")
_DISC_NUMBER = re.compile(r"\bdisc (\d+)\b")


class Backfill:
    def __init__(self, db: Database, discs: DiscStore, media: MediaStore, mb: MusicBrainz,
                 covers: Covers, tmdb: Tmdb, movies: Movies, tv_titles: TvTitles) -> None:
        self._db = db
        self._discs = discs
        self._media = media
        self._mb = mb
        self._covers = covers
        self._tmdb = tmdb
        self._movies = movies
        self._tv = tv_titles

    async def run(self) -> None:
        await asyncio.to_thread(self.fill)

    def fill(self) -> int:
        """Fill in every filed Disc missing its details; how many were filled."""
        filled = 0
        for rec in self._discs.list(DiscStatus.FILED, include_dismissed=True):
            if self._media.get(rec.id) is not None:
                continue
            try:
                done = self._cd(rec) if rec.disc_type == DiscType.CD else self._video(rec)
            except (httpx.HTTPError, OSError) as e:
                log.warning("History details for Disc %s not filled in yet (%s)", rec.id,
                            type(e).__name__)
                continue
            if done:
                filled += 1
                log.info("History details filled in for Disc %s (%s)", rec.id, rec.title)
        return filled

    def _cd(self, rec: DiscRecord) -> bool:
        disc_id = self._disc_id(rec.id)
        found = self._release(rec.id)
        if disc_id is None or found is None:
            return False
        release_id, number = found
        response = self._mb.lookup(disc_id)
        candidates = [m for m in matches(response or {}, disc_id) if m.release.id == release_id]
        match = next((m for m in candidates if m.disc_number == number),
                     candidates[0] if candidates else None)
        if match is None:
            return False
        self._media.save(rec.id, Album.of(match, disc_id, self._covers.release(match.release)))
        return True

    def _video(self, rec: DiscRecord) -> bool:
        if movie := self._movies.get(rec.id):
            tv, tmdb_id, title, year = False, movie.film.id, movie.film.title, movie.film.year
        elif rows := self._tv.for_disc(rec.id):
            series = rows[0].series
            # An Extras Disc's rows are its film's Extras, filed under Movies/.
            tv = any(r.episode for r in rows) or rows[0].path.parts[0] != "Movies"
            tmdb_id, title, year = series.id, series.name, series.year
        else:
            return False
        trouble: list[str] = []
        found = screen(self._tmdb, self._covers, tv, tmdb_id, title, year, trouble.append)
        if trouble:  # TMDB couldn't be asked: try again next start rather than keep less
            log.warning("History details for Disc %s not filled in yet (%s)", rec.id, trouble[0])
            return False
        self._media.save(rec.id, found)
        return True

    def _disc_id(self, disc_id: int) -> str | None:
        row = self._db.execute("SELECT fingerprint FROM disc_fingerprints WHERE disc_id = ?",
                               (disc_id,)).fetchone()
        prefix = f"{DiscType.CD}:"
        return row[0][len(prefix):] if row and row[0].startswith(prefix) else None

    def _release(self, disc_id: int) -> tuple[str, int] | None:
        """The release and disc number the CD was filed as, from its Disc log."""
        for line in reversed(self._discs.log_lines(disc_id)):
            if m := _RELEASE.search(line.text):
                n = _DISC_NUMBER.search(line.text)
                return m.group(1), int(n.group(1)) if n else 1
        return None
