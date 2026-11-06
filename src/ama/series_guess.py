"""A TV Job's Best guess: the series it most likely is, kept on the Job.

When the user marks a Disc as TV while it rips, TMDB is searched for the series named
by the Disc (season and disc numbers dropped, `tv.series_terms`; nothing for a generic
label). The user can search TMDB from the rip card and pick another series; a pick is
stored at once and no automatic guess replaces it. TV Review starts from the guess.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import httpx

from ama.covers import Covers
from ama.db import Database
from ama.film_guess import is_generic_label
from ama.jobs import JobRecord
from ama.tmdb import Series, Tmdb, TmdbError, load_hints
from ama.tv import series_terms


@dataclass(frozen=True)
class SeriesGuess:
    series: Series
    poster: str | None = None  # cached file name (covers.py)
    picked: bool = False       # the user chose it on the rip card

    @property
    def name(self) -> str:
        return self.series.title


def _to_json(s: Series) -> str:
    return json.dumps({"id": s.id, "name": s.name, "year": s.year,
                       "original_language": s.original_language}, ensure_ascii=False)


class SeriesGuesses:
    """The `series_guesses` table (migration 0023) and the TMDB searches that fill it."""

    def __init__(self, db: Database, tmdb: Tmdb, covers: Covers) -> None:
        self._db = db
        self._tmdb = tmdb
        self._covers = covers

    def get(self, job_id: int) -> SeriesGuess | None:
        row = self._db.execute("SELECT series, poster, picked FROM series_guesses "
                               "WHERE job_id = ?", (job_id,)).fetchone()
        return SeriesGuess(Series(**json.loads(row[0])), row[1], bool(row[2])) if row else None

    def guess(self, rec: JobRecord) -> None:
        """TMDB's first series for the Disc's names, unless the user picked one; nothing
        without a key, for a generic label, or when TMDB can't be asked."""
        if not self._tmdb.configured or self.get(rec.id) is not None:
            return
        terms = [t for t in series_terms(load_hints(rec.scratch_dir, rec.label))
                 if not is_generic_label(t)]
        try:
            found = next((r[0] for t in terms if (r := self._tmdb.search_tv(t, limit=1))), None)
        except TmdbError:
            return
        if found is not None:
            self._store(rec.id, found, picked=False)

    def search(self, query: str) -> list[Series]:
        """Series for the rip card's search. Raises TmdbError."""
        return self._tmdb.search_tv(query)

    def pick(self, job_id: int, series_id: int) -> SeriesGuess:
        """The user's choice, stored at once. Raises TmdbError."""
        return self._store(job_id, self._tmdb.series(series_id), picked=True)

    def _store(self, job_id: int, series: Series, picked: bool) -> SeriesGuess:
        guess = SeriesGuess(series, self._poster(series), picked)
        keep_pick = "" if picked else " WHERE series_guesses.picked = 0"
        self._db.execute(
            "INSERT INTO series_guesses (job_id, series, poster, picked) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (job_id) DO UPDATE SET series = excluded.series, "
            "poster = excluded.poster, picked = excluded.picked" + keep_pick,
            (job_id, _to_json(series), guess.poster, int(picked)))
        return guess

    def _poster(self, series: Series) -> str | None:
        """Its poster, cached; None when TMDB has none or can't be reached."""
        stem = f"tmdb-tv-{series.id}"
        if (cached := self._covers.cached(stem)) is not None:
            return cached
        try:
            _, path = self._tmdb.overview(True, series.id)
            data = self._tmdb.poster(path) if path else None
        except (TmdbError, httpx.HTTPError, OSError):  # a guess shows without one
            return None
        return self._covers.store(stem, data, "jpg") if data else None
