"""Video multi-disc sets (#14).

A *set* is the Discs that file into one Plex folder: a TV series' season
(`TV/Show (Year) {tmdb-ID}/Season NN`), or a film (`Movies/Title (Year) {tmdb-ID}`)
with its bonus Discs. A set exists once one of its Discs is filed; Review asks a
later Disc whether it belongs to one ("Is this Disc part of a set?") and which Disc
of the set it is. Attached, it reuses the set's Identification: a TV Disc's Episode
mapping starts at the set's series and season and carries on after the Episodes
earlier Discs filed; a bonus Disc's Titles are all filed as Extras in the film's
`Other/` folder.

Membership comes from what was filed (`tv_titles` Episodes, `movies`) plus the Disc
numbers recorded in `disc_sets`. A filed Disc with no recorded number gets the
lowest free number, in filing order. The answer to the question is kept in scratch
`set.json` until the Disc is filed, so it is asked once.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath

from ama.archive import safe_name
from ama.db import Database
from ama.discs import DiscRecord
from ama.tmdb import Candidate, Series, movie_folder
from ama.tv import season_folder, series_folder

ANSWER_FILE = "set.json"


class Library(StrEnum):
    TV = "tv"
    MOVIE = "movie"


@dataclass(frozen=True)
class SetKey:
    library: Library
    tmdb_id: int
    season: int | None = None  # TV only

    def __str__(self) -> str:
        """"tv:2996:1", "movie:438631" (the form value)."""
        return ":".join(str(p) for p in (self.library.value, self.tmdb_id, self.season)
                        if p is not None)

    @classmethod
    def parse(cls, text: str) -> SetKey | None:
        parts = text.split(":")
        try:
            library = Library(parts[0])
            numbers = [int(p) for p in parts[1:]]
        except ValueError:
            return None
        if library == Library.TV and len(numbers) == 2:
            return cls(library, numbers[0], numbers[1])
        if library == Library.MOVIE and len(numbers) == 1:
            return cls(library, numbers[0])
        return None


@dataclass(frozen=True)
class DiscSet:
    key: SetKey
    show: Series  # the series; for a film set, the film (id, title, year, language)
    members: tuple[tuple[int, int], ...]  # (disc id, Disc number), by number

    @property
    def name(self) -> str:
        """"The Office (2001) · Season 1", "Dune (2021)"."""
        if self.key.season is None:
            return self.show.title
        return f"{self.show.title} · Season {self.key.season}"

    @property
    def folder(self) -> PurePosixPath:
        """The set's Plex folder, relative to the Archive root."""
        if self.key.season is None:
            return PurePosixPath(*movie_folder(film(self.show)).parts)
        return series_folder(self.show) / season_folder(self.key.season)

    @property
    def numbers(self) -> list[int]:
        return [n for _, n in self.members]

    @property
    def next_number(self) -> int:
        return max(self.numbers, default=0) + 1

    @property
    def filed_text(self) -> str:
        """"Disc 1 filed", "Discs 1–2 filed", "Discs 1, 3 filed"."""
        ns = self.numbers
        if len(ns) == 1:
            return f"Disc {ns[0]} filed"
        if ns == list(range(ns[0], ns[-1] + 1)):
            return f"Discs {ns[0]}–{ns[-1]} filed"
        return f"Discs {', '.join(map(str, ns))} filed"

    def number_of(self, disc_id: int) -> int | None:
        return next((n for d, n in self.members if d == disc_id), None)


def bonus_path(film_set: DiscSet, disc_label: str, title_number: int) -> PurePosixPath:
    """Where a bonus Disc's Title is filed: `<film folder>/Other/<label> - Title N.mkv`."""
    return (film_set.folder / "Other"
            / f"{safe_name(disc_label or 'Disc')} - Title {title_number}.mkv")


def film(show: Series) -> Candidate:
    """A film set's film, as the movie pipeline names it."""
    return Candidate(show.id, show.name, "", show.year, show.original_language, 0)


def _norm(text: str) -> str:
    return re.sub(r"[\W_]+", " ", text.casefold()).strip()


def matching(sets: Iterable[DiscSet], terms: Iterable[str]) -> list[DiscSet]:
    """The sets whose series/film name is in one of the Disc's names (or the reverse)."""
    names = [n for n in (_norm(t) for t in terms) if n]
    out = []
    for s in sets:
        want = _norm(s.show.name)
        if want and any(f" {want} " in f" {n} " or f" {n} " in f" {want} " for n in names):
            out.append(s)
    return out


@dataclass(frozen=True)
class Answer:
    """What Review was told: attached to `key` as Disc `number`, or (key None) on its own."""

    key: SetKey | None
    number: int = 0


def answer(rec: DiscRecord) -> Answer | None:
    """The saved answer to "Is this Disc part of a set?", None if not asked yet."""
    try:
        data = json.loads((rec.scratch_dir / ANSWER_FILE).read_text(encoding="utf-8"))
        key = SetKey.parse(data["set"]) if data["set"] else None
        return Answer(key, int(data.get("disc", 0)))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save_answer(rec: DiscRecord, ans: Answer) -> None:
    tmp = rec.scratch_dir / f"{ANSWER_FILE}.tmp"
    tmp.write_text(json.dumps({"set": str(ans.key) if ans.key else None, "disc": ans.number}),
                   encoding="utf-8")
    tmp.replace(rec.scratch_dir / ANSWER_FILE)


class DiscSets:
    def __init__(self, db: Database) -> None:
        self._db = db

    def attach(self, disc_id: int, key: SetKey, number: int) -> None:
        """Record the Disc as Disc `number` of the set (idempotent; replaces an earlier one)."""
        self._db.execute(
            "INSERT INTO disc_sets (disc_id, library, tmdb_id, season, disc_number) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT (disc_id) DO UPDATE SET "
            "library = excluded.library, tmdb_id = excluded.tmdb_id, "
            "season = excluded.season, disc_number = excluded.disc_number",
            (disc_id, key.library.value, key.tmdb_id, key.season, number))

    def detach(self, disc_id: int) -> None:
        self._db.execute("DELETE FROM disc_sets WHERE disc_id = ?", (disc_id,))

    def filed(self, library: Library) -> list[DiscSet]:
        """Every set with a filed Disc, most recently filed first."""
        recorded = {(lib, tmdb_id, season, disc_id): number
                    for lib, tmdb_id, season, disc_id, number in self._db.execute(
                        "SELECT library, tmdb_id, season, disc_id, disc_number FROM disc_sets"
                    ).fetchall()}
        if library == Library.TV:
            rows = self._db.execute(
                "SELECT DISTINCT t.tmdb_id, t.series, t.year, t.original_language, t.season, "
                "t.disc_id, d.filed_at FROM tv_titles t JOIN discs d ON d.id = t.disc_id "
                "WHERE d.status = 'filed' AND t.season > 0 AND t.path LIKE 'TV/%'").fetchall()
            found = [(SetKey(Library.TV, r[0], r[4]), Series(r[0], r[1], r[2], r[3]), r[5], r[6])
                     for r in rows]
        else:
            rows = self._db.execute(
                "SELECT m.tmdb_id, m.title, m.year, m.original_language, m.disc_id, d.filed_at "
                "FROM movies m JOIN discs d ON d.id = m.disc_id WHERE d.status = 'filed'"
            ).fetchall()
            found = [(SetKey(Library.MOVIE, r[0]), Series(r[0], r[1], r[2], r[3]), r[4], r[5])
                     for r in rows]
            # bonus Discs: attached to a film, filed as its Extras
            shows = {k: s for k, s, _, _ in found}
            for lib, tmdb_id, _, disc_id in recorded:
                key = SetKey(Library.MOVIE, tmdb_id)
                if lib == Library.MOVIE.value and key in shows:
                    row = self._db.execute("SELECT filed_at FROM discs WHERE id = ? AND "
                                           "status = 'filed'", (disc_id,)).fetchone()
                    if row:
                        found.append((key, shows[key], disc_id, row[0]))
        by_key: dict[SetKey, tuple[Series, dict[int, str]]] = {}
        for key, show, disc_id, filed_at in found:
            by_key.setdefault(key, (show, {}))[1][disc_id] = filed_at or ""
        sets = []
        for key, (show, discs) in by_key.items():
            order = sorted(discs, key=lambda d: (discs[d], d))
            numbers = {d: n for d in order
                       if (n := recorded.get((key.library.value, key.tmdb_id, key.season, d)))}
            free = (n for n in range(1, 10_000) if n not in numbers.values())
            for d in order:
                if d not in numbers:
                    numbers[d] = next(free)
            members = tuple(sorted(numbers.items(), key=lambda m: (m[1], m[0])))
            sets.append((max(discs.values()), DiscSet(key, show, members)))
        return [s for _, s in sorted(sets, key=lambda x: x[0], reverse=True)]

    def find(self, key: SetKey) -> DiscSet | None:
        return next((s for s in self.filed(key.library) if s.key == key), None)
