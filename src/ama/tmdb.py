"""Movie Identification against TMDB (The Movie Database, API v3).

Search terms come from what the Disc says about itself: the Blu-ray metadata
title (`BDMV/META/DL/bdmt_*.xml`), MakeMKV's Disc name and the volume label,
cleaned of Disc-ish noise (`_DISC1`, `16X9`, `BLURAY`...). A TMDB result is a
candidate only when its title (or original title) is the search term, ignoring
case, punctuation and a leading article. It is accepted with no human only if
it is the *single* candidate whose runtime is within ±5 minutes of the Main
Feature; anything else goes to Review.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx

from ama.archive import safe_name
from ama.discs import ReviewReason

BASE = "https://api.themoviedb.org/3"
IMAGES = "https://image.tmdb.org/t/p"
MOVIES = Path("Movies")
RUNTIME_TOLERANCE_S = 5 * 60
MAX_DETAILS = 8  # /movie/{id} calls per Disc


@dataclass(frozen=True)
class DiscHints:
    """What the Disc says it is (saved to scratch at Rip time)."""

    volume_label: str = ""
    disc_name: str = ""     # MakeMKV's name for the Disc (CINFO 2)
    bd_title: str = ""      # Blu-ray metadata title
    volume_name: str = ""   # MakeMKV's volume name (CINFO 32)


HINTS_FILE = "disc.json"  # in the Disc's scratch folder


def save_hints(scratch_dir: Path, hints: DiscHints) -> None:
    (scratch_dir / HINTS_FILE).write_text(json.dumps(asdict(hints), ensure_ascii=False),
                                          encoding="utf-8")


def load_hints(scratch_dir: Path, volume_label: str) -> DiscHints:
    """The saved hints; just the volume label if the Rip predates them."""
    try:
        data = json.loads((scratch_dir / HINTS_FILE).read_text(encoding="utf-8"))
        return DiscHints(**{k: str(v) for k, v in data.items() if k in DiscHints.__dataclass_fields__})
    except (OSError, ValueError, TypeError):
        return DiscHints(volume_label=volume_label)


@dataclass(frozen=True)
class Candidate:
    id: int
    title: str
    original_title: str
    year: int | None
    original_language: str  # ISO 639-1
    runtime_min: int        # 0 = TMDB doesn't know
    director: str = ""      # shown in Review to tell same-named films apart

    @property
    def name(self) -> str:
        """How it is filed and shown: "Arrival (2016)"."""
        return f"{self.title} ({self.year})" if self.year else self.title

    def to_json(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Series:
    """A TV series on TMDB (#13)."""

    id: int
    name: str
    year: int | None               # of its first air date
    original_language: str = ""    # ISO 639-1
    seasons: tuple[int, ...] = ()  # season numbers TMDB has (0 = specials); () = not fetched

    @property
    def title(self) -> str:
        """How it is shown and filed: "The Office (2001)"."""
        return f"{self.name} ({self.year})" if self.year else self.name


@dataclass(frozen=True)
class Episode:
    season: int   # 0 = specials
    number: int
    name: str
    runtime_min: int = 0  # 0 = TMDB doesn't know

    @property
    def code(self) -> str:
        return f"S{self.season:02d}E{self.number:02d}"


def _year(date: str | None) -> int | None:
    return int(date[:4]) if date and date[:4].isdigit() else None


_JUNK = re.compile(
    r"^(disc|disk|dvd|bd|bluray|blu-ray|uhd|4k|hd|ws|fs|widescreen|fullscreen|16x9|4x3|ntsc|"
    r"pal|r[0-9]|video|edition|special|se|d[0-9]|disc[0-9]+|disk[0-9]+|cd[0-9]?|[0-9]+of[0-9]+)$",
    re.I)


def clean_term(text: str) -> str:
    """A Disc name as a search term: separators to spaces, trailing Disc noise dropped."""
    t = re.sub(r"[™®©]", "", text)
    t = re.sub(r"[_.]+", " ", t)
    words = t.split()
    while words and (_JUNK.match(words[-1]) or words[-1] in {"-", "–", ":"}):
        words.pop()
    return " ".join(words).strip(" -–:")


def search_terms(hints: DiscHints) -> list[str]:
    """Distinct search terms, most trustworthy first."""
    out: list[str] = []
    for raw in (hints.bd_title, hints.disc_name, hints.volume_label, hints.volume_name):
        term = clean_term(raw)
        if term and term.casefold() not in {t.casefold() for t in out}:
            out.append(term)
    return out


def _norm(title: str) -> str:
    t = re.sub(r"[\W_]+", " ", title.casefold()).strip()
    return re.sub(r"^(the|a|an) ", "", t)


def title_matches(result: dict, term: str) -> bool:
    want = _norm(term)
    return bool(want) and want in {_norm(result.get("title") or ""),
                                   _norm(result.get("original_title") or "")}


def decide(candidates: list[Candidate], main_feature_s: int
           ) -> tuple[Candidate | None, ReviewReason | None]:
    """(the accepted film, None), or (None, why it needs Review)."""
    if not candidates:
        return None, ReviewReason.NO_MATCH
    fits = {c.id: c for c in candidates
            if c.runtime_min and abs(c.runtime_min * 60 - main_feature_s) <= RUNTIME_TOLERANCE_S}
    if not fits:
        return None, ReviewReason.RUNTIME_MISMATCH
    if len(fits) > 1:
        return None, ReviewReason.MULTIPLE_MATCHES
    return next(iter(fits.values())), None


def movie_folder(c: Candidate) -> Path:
    """`Movies/Title (Year) {tmdb-ID}` (Plex naming)."""
    return MOVIES / movie_file_stem(c)


def movie_file_stem(c: Candidate) -> str:
    return f"{safe_name(c.name)} {{tmdb-{c.id}}}"


_BDMT_NAME = re.compile(r"<di:name>(.*?)</di:name>", re.S)


def bd_meta_title(disc_root: Path) -> str:
    """The Blu-ray's own title from BDMV/META/DL (English first), or ""."""
    dl = disc_root / "BDMV" / "META" / "DL"
    try:
        files = sorted(dl.glob("bdmt_*.xml"), key=lambda p: (p.name.lower() != "bdmt_eng.xml",
                                                             p.name))
        for f in files:
            m = _BDMT_NAME.search(f.read_text(encoding="utf-8", errors="replace"))
            if m and m.group(1).strip():
                return html.unescape(m.group(1).strip())
    except OSError:
        pass
    return ""


class TmdbError(Exception):
    """TMDB couldn't be asked (network, bad key). The message never contains the key."""


class Tmdb:
    def __init__(self, http: httpx.Client, api_key: str) -> None:
        self._http = http
        self._key = api_key

    @property
    def configured(self) -> bool:
        return bool(self._key)

    def _get(self, path: str, params: dict) -> dict:
        # A v4 read-access token (a JWT) goes in the header; a v3 key has to be a param.
        headers = {"Accept": "application/json"}
        if self._key.startswith("eyJ"):
            headers["Authorization"] = f"Bearer {self._key}"
        else:
            params = {**params, "api_key": self._key}
        try:
            r = self._http.get(f"{BASE}{path}", params=params, headers=headers)
        except httpx.HTTPError as e:
            raise TmdbError(f"Couldn't reach TMDB ({type(e).__name__})") from None
        if r.status_code == 401:
            raise TmdbError("TMDB refused the API key in ama.toml")
        if r.status_code != 200:
            raise TmdbError(f"TMDB answered HTTP {r.status_code}")
        return r.json()

    def movie(self, movie_id: int, found: dict | None = None) -> Candidate:
        """One film's details (`found`: its search result, for fields the details lack)."""
        r = found or {}
        d = self._get(f"/movie/{movie_id}", {"append_to_response": "credits"})
        date = d.get("release_date") or r.get("release_date") or ""
        crew = (d.get("credits") or {}).get("crew") or []
        return Candidate(
            id=int(movie_id), title=d.get("title") or r.get("title") or "",
            original_title=d.get("original_title") or "",
            year=int(date[:4]) if date[:4].isdigit() else None,
            original_language=d.get("original_language") or r.get("original_language") or "",
            runtime_min=int(d.get("runtime") or 0),
            director=", ".join(c["name"] for c in crew
                               if c.get("job") == "Director" and c.get("name"))[:80])

    def candidates(self, terms: list[str]) -> list[Candidate]:
        """Films titled like one of `terms`, with their runtimes. Raises TmdbError."""
        found: dict[int, Candidate] = {}
        for term in terms:
            results = self._get("/search/movie", {"query": term, "include_adult": "false"})
            for r in results.get("results", []):
                if r.get("id") in found or len(found) >= MAX_DETAILS or not title_matches(r, term):
                    continue
                found[int(r["id"])] = self.movie(int(r["id"]), {"title": term, **r})
        return list(found.values())

    def search(self, query: str, limit: int = MAX_DETAILS) -> list[Candidate]:
        """TMDB's best `limit` films for a free-text search (Review). Raises TmdbError."""
        results = self._get("/search/movie", {"query": query, "include_adult": "false"})
        return [self.movie(int(r["id"]), r) for r in results.get("results", [])[:limit]
                if r.get("id")]

    # -- TV (#13) -------------------------------------------------------------

    def search_tv(self, query: str, limit: int = MAX_DETAILS) -> list[Series]:
        """TMDB's best `limit` series for a free-text search. Raises TmdbError."""
        results = self._get("/search/tv", {"query": query, "include_adult": "false"})
        return [Series(int(r["id"]), r.get("name") or r.get("original_name") or "",
                       _year(r.get("first_air_date")), r.get("original_language") or "")
                for r in results.get("results", [])[:limit] if r.get("id")]

    def series(self, series_id: int) -> Series:
        """One series with its season numbers. Raises TmdbError."""
        d = self._get(f"/tv/{series_id}", {})
        return Series(int(series_id), d.get("name") or d.get("original_name") or "",
                      _year(d.get("first_air_date")), d.get("original_language") or "",
                      tuple(sorted(int(s["season_number"]) for s in d.get("seasons") or []
                                   if s.get("season_number") is not None)))

    def season(self, series_id: int, number: int) -> list[Episode]:
        """A season's Episodes in order (season 0 = specials). Raises TmdbError."""
        d = self._get(f"/tv/{series_id}/season/{number}", {})
        return sorted((Episode(int(e.get("season_number", number)), int(e["episode_number"]),
                               e.get("name") or "", int(e.get("runtime") or 0))
                       for e in d.get("episodes") or [] if e.get("episode_number") is not None),
                      key=lambda e: e.number)

    # -- History (what a filed Disc is) ---------------------------------------

    def overview(self, tv: bool, tmdb_id: int) -> tuple[str, str | None]:
        """A film's or series' overview and poster path ("/abc.jpg"). Raises TmdbError."""
        d = self._get(f"/{'tv' if tv else 'movie'}/{tmdb_id}", {})
        return d.get("overview") or "", d.get("poster_path") or None

    def poster(self, path: str) -> bytes | None:
        """A poster image (342 px wide), or None if TMDB has none at `path`.
        Raises httpx.HTTPError when it can't be fetched."""
        r = self._http.get(f"{IMAGES}/w342{path}", follow_redirects=True)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.content

    def guess(self, volume_label: str) -> Candidate | None:
        """A likely film for a Disc being ripped, from its volume label alone (only for show:
        Identification decides). None when TMDB has none or can't be asked."""
        terms = search_terms(DiscHints(volume_label=volume_label))
        if not self.configured or not terms:
            return None
        try:
            found = self.search(terms[0], limit=1)
        except TmdbError:
            return None
        return found[0] if found else None
