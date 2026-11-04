"""CD Identification against MusicBrainz: Disc ID lookup, and which releases it names.

A Disc ID identifies one medium (disc) of a release. The lookup returns every
release with a medium carrying that Disc ID; each such (release, medium) pair is
a `Match`. The disc number is that medium's position, never assumed to be 1.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from importlib.metadata import version
from typing import Any

import httpx

USER_AGENT = (f"AMA/{version('ama')} "
              "( https://git.mintopia.net/mintopia/automatic-media-archive )")

VARIOUS_ARTISTS = "89ad4ac3-39f7-470e-963a-56509c546377"  # MusicBrainz's special artist


@dataclass(frozen=True)
class Release:
    id: str
    title: str
    artist: str                   # album artist credit as printed, e.g. "Various Artists"
    artist_ids: tuple[str, ...]
    disc_total: int
    date: str | None = None
    country: str | None = None
    barcode: str | None = None
    status: str | None = None
    release_group_id: str | None = None
    labels: tuple[tuple[str, str], ...] = ()  # (label name, catalogue number)
    disambiguation: str | None = None  # e.g. "English track titles"
    has_front: bool | None = None      # the Cover Art Archive has a front cover (None = unknown)

    @property
    def is_compilation(self) -> bool:
        return self.artist_ids == (VARIOUS_ARTISTS,)


@dataclass(frozen=True)
class TrackInfo:
    number: int  # position on its disc
    title: str
    artist: str
    artist_ids: tuple[str, ...]
    recording_id: str
    track_id: str


@dataclass(frozen=True)
class Match:
    """One release this Disc could be: which of its discs, with that disc's tracks."""

    release: Release
    disc_number: int
    disc_title: str
    tracks: tuple[TrackInfo, ...]


def _credit(credits: list[dict[str, Any]]) -> tuple[str, tuple[str, ...]]:
    name = "".join(c.get("name", "") + c.get("joinphrase", "") for c in credits)
    return name, tuple(c["artist"]["id"] for c in credits if c.get("artist"))


def _release(r: dict[str, Any]) -> Release:
    artist, artist_ids = _credit(r.get("artist-credit", []))
    labels = tuple(((li.get("label") or {}).get("name", ""), li.get("catalog-number") or "")
                   for li in r.get("label-info", []))
    return Release(
        id=r["id"], title=r["title"], artist=artist, artist_ids=artist_ids,
        disc_total=len(r.get("media", [])), date=r.get("date") or None,
        country=r.get("country") or None, barcode=r.get("barcode") or None,
        status=r.get("status") or None,
        release_group_id=(r.get("release-group") or {}).get("id"), labels=labels,
        disambiguation=r.get("disambiguation") or None,
        has_front=(r.get("cover-art-archive") or {}).get("front"),
    )


def _track(t: dict[str, Any]) -> TrackInfo:
    rec = t.get("recording") or {}
    artist, artist_ids = _credit(t.get("artist-credit") or rec.get("artist-credit") or [])
    return TrackInfo(number=t["position"], title=t.get("title") or rec.get("title", ""),
                     artist=artist, artist_ids=artist_ids, recording_id=rec.get("id", ""),
                     track_id=t["id"])


class MusicBrainz:
    """The MusicBrainz and Cover Art Archive web services, over one shared httpx client.

    The client must carry AMA's User-Agent (MusicBrainz requires contact info).
    Requests to MusicBrainz are spaced `min_interval` apart (its limit is 1/s per IP).
    Network errors and 5xx raise httpx.HTTPError: the caller retries later.
    """

    BASE = "https://musicbrainz.org/ws/2"
    CAA = "https://coverartarchive.org"
    INC = "recordings+artist-credits+labels+release-groups"

    def __init__(self, http: httpx.Client, min_interval: float = 1.1) -> None:
        self._http = http
        self.min_interval = min_interval
        self._last = -min_interval
        self._lock = threading.Lock()

    def lookup(self, disc_id: str) -> dict[str, Any] | None:
        """The `/ws/2/discid` response, or None if MusicBrainz doesn't know the Disc."""
        with self._lock:
            wait = self._last + self.min_interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            try:
                # Built by hand: MusicBrainz wants literal `+` between inc values.
                r = self._http.get(f"{self.BASE}/discid/{disc_id}?inc={self.INC}"
                                   "&fmt=json&cdstubs=no")
            finally:
                self._last = time.monotonic()
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    def cover_art(self, release: Release) -> tuple[bytes, str] | None:
        """The front cover as (image bytes, file extension), or None if there is none."""
        urls = [f"{self.CAA}/release/{release.id}/front-1200",
                f"{self.CAA}/release/{release.id}/front"]
        if release.release_group_id:
            urls.append(f"{self.CAA}/release-group/{release.release_group_id}/front-1200")
        for url in urls:
            r = self._http.get(url, follow_redirects=True)
            if r.status_code in (400, 404):
                continue
            r.raise_for_status()
            ext = "png" if "png" in r.headers.get("content-type", "") else "jpg"
            return r.content, ext
        return None


def matches(response: dict[str, Any], disc_id: str) -> list[Match]:
    """Every (release, disc) in a `/ws/2/discid` response whose medium carries `disc_id`."""
    out: list[Match] = []
    for r in response.get("releases", []):
        release = _release(r)
        for medium in r.get("media", []):
            if any(d.get("id") == disc_id for d in medium.get("discs", [])):
                out.append(Match(release, medium["position"], medium.get("title") or "",
                                 tuple(_track(t) for t in medium.get("tracks", []))))
    return out
