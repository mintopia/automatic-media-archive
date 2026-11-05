"""A video Job's Best guess: the film it most likely is, kept on the Job.

While a Disc rips, TMDB is searched for its volume label (unless the label is
generic, `DVD_VIDEO`, `DISC1`...: then there is no guess and the rip card asks
the user to pick a title). Once the Title scan knows the longest Title, the
results are re-ranked by how close each film's runtime is to it. The user can
search TMDB from the rip card and pick another film; a pick is stored at once
and no automatic guess replaces it. Review starts from the Best guess. Only
Identification (and Review) decide what a Disc is: a guess is a starting point.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import httpx

from ama.covers import Covers
from ama.db import Database
from ama.tmdb import Candidate, DiscHints, Tmdb, TmdbError, clean_term, search_terms

GUESS_RESULTS = 5  # films asked of TMDB for a guess (each costs a /movie/{id} call)

# Volume labels that say nothing about the film (after `clean_term`, case-folded).
GENERIC_LABELS = frozenset({
    "dvd video", "video ts", "bdrom", "bd rom", "bdmv", "blu ray", "bluray", "movie", "film",
    "main", "feature", "untitled", "no name", "noname", "no label", "nolabel", "volume",
    "new volume", "logical volume id", "dvdvolume", "dvd volume", "disc", "disk", "cdrom",
})


def is_generic_label(label: str) -> bool:
    """A volume label that names no film: searching TMDB for it gives a wrong poster."""
    term = clean_term(label).casefold()
    return not term or term in GENERIC_LABELS or term.replace(" ", "").isdigit()


def by_runtime(films: list[Candidate], duration_s: int | None) -> list[Candidate]:
    """Closest runtime to `duration_s` first (films without one last); TMDB's order on ties
    and when the duration isn't known yet."""
    if not duration_s:
        return list(films)
    return sorted(films, key=lambda f: abs(f.runtime_min * 60 - duration_s) if f.runtime_min
                  else float("inf"))


@dataclass(frozen=True)
class FilmGuess:
    film: Candidate
    poster: str | None = None  # cached file name (covers.py)
    picked: bool = False       # the user chose it on the rip card

    @property
    def name(self) -> str:
        return self.film.name


class FilmGuesses:
    """The `film_guesses` table (migration 0014) and the TMDB searches that fill it."""

    def __init__(self, db: Database, tmdb: Tmdb, covers: Covers) -> None:
        self._db = db
        self._tmdb = tmdb
        self._covers = covers

    @property
    def configured(self) -> bool:
        return self._tmdb.configured

    def get(self, job_id: int) -> FilmGuess | None:
        row = self._db.execute("SELECT film, poster, picked FROM film_guesses WHERE job_id = ?",
                               (job_id,)).fetchone()
        return FilmGuess(Candidate(**json.loads(row[0])), row[1], bool(row[2])) if row else None

    # -- automatic -------------------------------------------------------------

    def candidates(self, label: str) -> list[Candidate]:
        """TMDB's films for a volume label; [] for a generic label, without a key, or when
        TMDB can't be asked (a guess is never worth an error)."""
        terms = search_terms(DiscHints(volume_label=label))
        if not self.configured or not terms or is_generic_label(label):
            return []
        try:
            return self._tmdb.search(terms[0], limit=GUESS_RESULTS)
        except TmdbError:
            return []

    def settle(self, job_id: int, films: list[Candidate], duration_s: int | None) -> None:
        """Keep the best of `films` for `duration_s` as the Job's guess, unless the user
        picked one."""
        ranked = by_runtime(films, duration_s)
        if not ranked:
            return
        guess = FilmGuess(ranked[0], self._poster(ranked[0]))
        self._db.execute(
            "INSERT INTO film_guesses (job_id, film, poster, picked) VALUES (?, ?, ?, 0) "
            "ON CONFLICT (job_id) DO UPDATE SET film = excluded.film, poster = excluded.poster "
            "WHERE film_guesses.picked = 0",
            (job_id, json.dumps(guess.film.to_json(), ensure_ascii=False), guess.poster))

    # -- the user's -------------------------------------------------------------

    def search(self, query: str, duration_s: int | None) -> list[Candidate]:
        """Films for the rip card's search, closest runtime first. Raises TmdbError."""
        return by_runtime(self._tmdb.search(query), duration_s)

    def pick(self, job_id: int, film_id: int) -> FilmGuess:
        """The user's choice, stored at once. Raises TmdbError."""
        film = self._tmdb.movie(film_id)
        guess = FilmGuess(film, self._poster(film), picked=True)
        self._db.execute(
            "INSERT INTO film_guesses (job_id, film, poster, picked) VALUES (?, ?, ?, 1) "
            "ON CONFLICT (job_id) DO UPDATE SET film = excluded.film, poster = excluded.poster, "
            "picked = 1",
            (job_id, json.dumps(film.to_json(), ensure_ascii=False), guess.poster))
        return guess

    def _poster(self, film: Candidate) -> str | None:
        """Its poster, cached; None when TMDB has none or can't be reached."""
        stem = f"tmdb-movie-{film.id}"
        if (cached := self._covers.cached(stem)) is not None:
            return cached
        try:
            _, path = self._tmdb.overview(False, film.id)
            data = self._tmdb.poster(path) if path else None
        except (TmdbError, httpx.HTTPError, OSError):  # a guess shows without one
            return None
        return self._covers.store(stem, data, "jpg") if data else None
