"""What a filed Disc is, kept at filing time for its History page.

An `Album` (CD, from the MusicBrainz match it was filed as) or a `Screen` (film or
TV series, from TMDB). Stored as JSON in `media_info` (migration 0012), with any
cover or poster cached by `covers.Covers`, so the page needs neither scratch
(deleted on filing) nor a live web request.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Literal

import httpx

from ama.covers import Covers
from ama.db import Database
from ama.musicbrainz import Match
from ama.tmdb import Tmdb, TmdbError

MB = "https://musicbrainz.org"
CAA = "https://coverartarchive.org"
TMDB = "https://www.themoviedb.org"


@dataclass(frozen=True)
class AlbumTrack:
    number: int
    title: str
    artist: str


@dataclass(frozen=True)
class Album:
    title: str
    artist: str
    disc_number: int
    disc_total: int
    tracks: tuple[AlbumTrack, ...]
    disc_id: str = ""              # MusicBrainz Disc ID
    release_id: str = ""           # "" = details entered by hand in Review
    release_group_id: str = ""
    disc_title: str = ""
    date: str = ""
    country: str = ""
    barcode: str = ""
    labels: tuple[tuple[str, str], ...] = ()  # (label, catalogue number)
    cover: str | None = None       # cached file name (covers.py)
    kind: Literal["album"] = "album"

    @classmethod
    def of(cls, match: Match, disc_id: str, cover: str | None) -> Album:
        r = match.release
        return cls(title=r.title, artist=r.artist, disc_number=match.disc_number,
                   disc_total=r.disc_total, disc_id=disc_id, release_id=r.id,
                   release_group_id=r.release_group_id or "", disc_title=match.disc_title,
                   date=r.date or "", country=r.country or "", barcode=r.barcode or "",
                   labels=tuple(dict.fromkeys(r.labels)), cover=cover,
                   tracks=tuple(AlbumTrack(t.number, t.title, t.artist) for t in match.tracks))

    @property
    def year(self) -> str:
        return self.date[:4]

    def track_title(self, number: int) -> str | None:
        return next((t.title for t in self.tracks if t.number == number), None)

    def track_artist(self, number: int) -> str | None:
        """The track's artist when it isn't the album artist (compilations)."""
        artist = next((t.artist for t in self.tracks if t.number == number), None)
        return artist if artist and artist != self.artist else None

    @property
    def links(self) -> list[tuple[str, str]]:
        out = []
        if self.release_id:
            out.append(("MusicBrainz release", f"{MB}/release/{self.release_id}"))
        if self.release_group_id:
            out.append(("Release group", f"{MB}/release-group/{self.release_group_id}"))
        if self.disc_id:
            out.append(("Disc ID", f"{MB}/cdtoc/{self.disc_id}"))
        if self.release_id:
            out.append(("Cover Art Archive", f"{CAA}/release/{self.release_id}"))
        return out

    @property
    def source(self) -> tuple[str, str, str] | None:
        """(name, short name, URL) of where it was identified; None if entered by hand."""
        if not self.release_id:
            return None
        return "MusicBrainz release", "MB", f"{MB}/release/{self.release_id}"


@dataclass(frozen=True)
class Screen:
    """A film or TV series a video Disc was filed as."""

    tmdb_id: int
    title: str
    year: int | None
    tv: bool = False
    overview: str = ""
    poster: str | None = None      # cached file name (covers.py)
    kind: Literal["screen"] = "screen"

    @property
    def name(self) -> str:
        return f"{self.title} ({self.year})" if self.year else self.title

    @property
    def links(self) -> list[tuple[str, str]]:
        return [("TMDB", f"{TMDB}/{'tv' if self.tv else 'movie'}/{self.tmdb_id}")]

    @property
    def source(self) -> tuple[str, str, str]:
        return "TMDB", "TMDB", self.links[0][1]


Media = Album | Screen


def to_json(info: Media) -> str:
    return json.dumps(asdict(info), ensure_ascii=False)


def from_json(text: str) -> Media:
    d = json.loads(text)
    if d.get("kind") == "screen":
        return Screen(**d)
    d["tracks"] = tuple(AlbumTrack(**t) for t in d.get("tracks", []))
    d["labels"] = tuple(tuple(x) for x in d.get("labels", []))
    return Album(**d)


class MediaStore:
    """The `media_info` table: one row per filed Disc."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def save(self, disc_id: int, info: Media) -> None:
        self._db.execute("INSERT INTO media_info (disc_id, info) VALUES (?, ?) "
                         "ON CONFLICT (disc_id) DO UPDATE SET info = excluded.info",
                         (disc_id, to_json(info)))

    def get(self, disc_id: int) -> Media | None:
        row = self._db.execute("SELECT info FROM media_info WHERE disc_id = ?",
                               (disc_id,)).fetchone()
        return from_json(row[0]) if row else None


def screen(tmdb: Tmdb, covers: Covers, tv: bool, tmdb_id: int, title: str, year: int | None,
           log: Callable[[str], None]) -> Screen:
    """What to keep for a filed film or series: TMDB's overview and poster, best effort.

    TMDB trouble is logged and leaves them out; it never holds up filing.
    """
    overview, poster = "", None
    try:
        overview, path = tmdb.overview(tv, tmdb_id)
        stem = f"tmdb-{'tv' if tv else 'movie'}-{tmdb_id}"
        poster = covers.cached(stem)
        if path and poster is None:
            data = tmdb.poster(path)
            poster = covers.store(stem, data, "jpg") if data else None
    except TmdbError as e:
        log(f"No overview or poster kept: {e}")
    except (httpx.HTTPError, OSError) as e:
        log(f"No poster kept: couldn't fetch it from TMDB ({type(e).__name__})")
    return Screen(tmdb_id, title, year, tv=tv, overview=overview, poster=poster)


def film_guess(tmdb: Tmdb, covers: Covers, volume_label: str) -> Screen | None:
    """A likely film for a Disc being ripped, with its poster cached; only for show."""
    film = tmdb.guess(volume_label)
    if film is None:
        return None
    return screen(tmdb, covers, False, film.id, film.title, film.year, lambda _: None)
