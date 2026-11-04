"""Extras (#8): every ripped Title of a movie Disc that isn't the Main Feature.

`MovieArchiver` Encodes them after the Main Feature and files them with it, to
`<film folder>/Other/<name>.mkv`, named from the Title's name on the Disc (Plex's
"Other" local extras folder). No Review is needed. Afterwards the user may sort
them (`/discs/{id}/extras`): a new category or name moves the file to that Plex
folder (`Featurettes/`, `Deleted Scenes/`, ...). Stills of each Extra are taken
from the Rip before it is deleted and kept beside the state database, so the
sorting page still has pictures once scratch is gone.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from ama import decoys
from ama.archive import safe_name
from ama.db import Database
from ama.discs import TitleRecord, TitleStatus


class Category(StrEnum):
    """Plex's local extras folders; the value is the folder name."""

    OTHER = "Other"
    FEATURETTES = "Featurettes"
    DELETED_SCENES = "Deleted Scenes"
    BEHIND_THE_SCENES = "Behind The Scenes"
    INTERVIEWS = "Interviews"
    SCENES = "Scenes"
    SHORTS = "Shorts"
    TRAILERS = "Trailers"


class ExtraStatus(StrEnum):
    QUEUED = "queued"
    ENCODING = "encoding"
    ENCODED = "encoded"  # waiting to be filed with the film
    FAILED = "failed"    # left out; the film is filed without it
    FILED = "filed"


@dataclass(frozen=True)
class Extra:
    disc_id: int
    title_number: int
    name: str            # the name in Plex
    category: Category
    status: ExtraStatus
    file: str            # 'Other/Name.mkv' relative to the film's folder, once chosen
    reviewed: bool

    @property
    def encoded(self) -> str:
        """The Encode's file name in the Disc's scratch."""
        return f"extra_t{self.title_number}.mkv"


def extra_titles(titles: Iterable[TitleRecord], main_feature: int) -> list[TitleRecord]:
    """The Disc's Extras: every ripped Title but the Main Feature and, on a Disc with
    decoy playlists (#9), the other near-identical versions of the film."""
    ripped = [t for t in titles if t.status == TitleStatus.RIPPED]
    found = decoys.detect(ripped)
    versions = {t.number for t in found.versions} if found else set()
    return [t for t in ripped if t.number != main_feature and t.number not in versions]


def default_names(titles: Iterable[TitleRecord], not_names: Iterable[str]) -> dict[int, str]:
    """{Title number: name in Plex}: the Title's name on the Disc, unless it's blank or just
    one of `not_names` (the Disc's or film's name, which MakeMKV gives every Title), then
    "Title N". A name several Extras share gets " (Title N)" so each file is distinct."""
    generic = {n.strip().casefold() for n in not_names if n.strip()}
    titles = list(titles)
    names = {t.number: (t.name.strip() if t.name.strip().casefold() not in generic | {""}
                        else f"Title {t.number}") for t in titles}
    counts: dict[str, int] = {}
    for name in names.values():
        counts[name.casefold()] = counts.get(name.casefold(), 0) + 1
    return {n: f"{name} (Title {n})" if counts[name.casefold()] > 1 else name
            for n, name in names.items()}


def file_name(category: Category, name: str, taken: Callable[[str], bool]) -> str:
    """'<Category>/<name>.mkv' (safe for Windows), numbered ' (2)' on if `taken`."""
    base = safe_name(name, limit=76)
    for i in range(1, 1000):
        rel = f"{category.value}/{base}{f' ({i})' if i > 1 else ''}.mkv"
        if not taken(rel):
            return rel
    raise ValueError(f"No free name for {name}")


STILLS = "extras"  # beside the state database: <dir>/<disc id>/t<title>_<pct>.jpg


class Extras:
    _COLS = "disc_id, title_number, name, category, status, file, reviewed"

    def __init__(self, db: Database, stills_dir: Path) -> None:
        self._db = db
        self.stills_dir = stills_dir

    def _extra(self, row) -> Extra:
        disc_id, number, name, category, status, file, reviewed = row
        return Extra(disc_id, number, name, Category(category), ExtraStatus(status), file,
                     bool(reviewed))

    def plan(self, disc_id: int, names: dict[int, str]) -> None:
        """The Disc's Extras, queued for Encode (idempotent: known ones are kept)."""
        for number, name in names.items():
            self._db.execute("INSERT OR IGNORE INTO extras (disc_id, title_number, name) "
                             "VALUES (?, ?, ?)", (disc_id, number, name))

    def of(self, disc_id: int) -> list[Extra]:
        rows = self._db.execute(f"SELECT {self._COLS} FROM extras WHERE disc_id = ? "
                                "ORDER BY title_number", (disc_id,)).fetchall()
        return [self._extra(r) for r in rows]

    def get(self, disc_id: int, number: int) -> Extra | None:
        row = self._db.execute(f"SELECT {self._COLS} FROM extras WHERE disc_id = ? AND "
                               "title_number = ?", (disc_id, number)).fetchone()
        return self._extra(row) if row else None

    def set_status(self, disc_id: int, number: int, status: ExtraStatus) -> None:
        self._db.execute("UPDATE extras SET status = ? WHERE disc_id = ? AND title_number = ?",
                         (status.value, disc_id, number))

    def place(self, disc_id: int, number: int, name: str, category: Category,
              file: str) -> None:
        """Record where the Extra is (or is about to be) in the film's folder."""
        self._db.execute("UPDATE extras SET name = ?, category = ?, file = ? "
                         "WHERE disc_id = ? AND title_number = ?",
                         (name, category.value, file, disc_id, number))

    def mark_reviewed(self, disc_id: int) -> None:
        self._db.execute("UPDATE extras SET reviewed = 1 WHERE disc_id = ?", (disc_id,))

    def to_sort(self) -> list[int]:
        """Filed Discs whose Extras nobody has looked at yet, oldest first."""
        rows = self._db.execute("SELECT DISTINCT disc_id FROM extras WHERE status = 'filed' "
                                "AND reviewed = 0 ORDER BY disc_id").fetchall()
        return [r[0] for r in rows]

    def requeue_unfinished(self) -> None:
        """At startup: Extra Encodes cut short go back in the queue."""
        self._db.execute("UPDATE extras SET status = 'queued' WHERE status = 'encoding'")

    def still(self, disc_id: int, number: int, pct: int) -> Path:
        return self.stills_dir / str(disc_id) / f"t{number}_{pct}.jpg"
