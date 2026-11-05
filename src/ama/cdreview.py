"""CD Review: what a human decided about a CD that couldn't be filed automatically.

A CD in Review has its Rip and MusicBrainz answer (`musicbrainz.json`) in scratch.
The user's `Decision` is saved next to them (`review.json`) and the Disc goes back
to `ripped`; `CdArchiver` then files it exactly as it files automatically, with
the same retries while the network or NAS is away. Any decision accepts the Rip
as it is, so AccurateRip problems don't send it back to Review.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ama import cyanrip, musicbrainz
from ama.cdrip import Track
from ama.cyanrip import ArStatus
from ama.musicbrainz import Match, Release, TrackInfo

DECISION_FILE = "review.json"
MB_FILE = "musicbrainz.json"


@dataclass(frozen=True)
class AcceptRip:
    """File it even though AccurateRip didn't verify every track."""


@dataclass(frozen=True)
class PickRelease:
    release_id: str
    disc_number: int


@dataclass(frozen=True)
class ManualDetails:
    album: str
    artist: str
    year: str  # "" = unknown
    titles: tuple[str, ...]  # tracks 1..n


Decision = AcceptRip | PickRelease | ManualDetails
_KINDS: dict[str, type[Decision]] = {"accept": AcceptRip, "pick": PickRelease,
                                     "manual": ManualDetails}


def save_decision(scratch: Path, decision: Decision) -> None:
    kind = next(k for k, cls in _KINDS.items() if isinstance(decision, cls))
    tmp = scratch / f"{DECISION_FILE}.tmp"
    tmp.write_text(json.dumps({"kind": kind, **asdict(decision)}, ensure_ascii=False),
                   encoding="utf-8")
    os.replace(tmp, scratch / DECISION_FILE)


def load_decision(scratch: Path) -> Decision | None:
    try:
        data = json.loads((scratch / DECISION_FILE).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    cls = _KINDS[data.pop("kind")]
    if cls is ManualDetails:
        data["titles"] = tuple(data["titles"])
    return cls(**data)


def saved_response(scratch: Path) -> dict[str, Any] | None:
    try:
        return json.loads((scratch / MB_FILE).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def mb_disc_id(scratch: Path) -> str:
    try:
        text = (scratch / "rip.log").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return cyanrip.parse_report(text).mb_disc_id or ""


def audio_tracks(tracks: list[Track]) -> list[Track]:
    """The numbered tracks (a hidden track 0 isn't on MusicBrainz or AccurateRip)."""
    return [t for t in tracks if t.number > 0]


def fitting(tracks: list[Track], candidates: list[Match]) -> list[Match]:
    """The matches whose disc has as many tracks as were ripped: the ones that can be filed."""
    n = len(audio_tracks(tracks))
    return [m for m in candidates if len(m.tracks) == n]


def candidates(scratch: Path, tracks: list[Track]) -> list[Match]:
    """The editions offered in Review: saved MusicBrainz matches that fit the Rip."""
    response = saved_response(scratch)
    return fitting(tracks, musicbrainz.matches(response, mb_disc_id(scratch))) if response else []


def unverified(tracks: list[Track], status: ArStatus) -> list[int]:
    """Numbers of the tracks whose AccurateRip result is `status` (no result = unavailable)."""
    return [t.number for t in audio_tracks(tracks)
            if (t.ar.status if t.ar else ArStatus.UNAVAILABLE) == status]


def manual_match(details: ManualDetails) -> Match:
    """A Match for filing from details entered by hand: disc 1 of 1, no MusicBrainz IDs."""
    release = Release(id="", title=details.album, artist=details.artist, artist_ids=(),
                      disc_total=1, date=details.year or None)
    return Match(release, 1, "", tuple(
        TrackInfo(number=i, title=title, artist=details.artist, artist_ids=(),
                  recording_id="", track_id="")
        for i, title in enumerate(details.titles, start=1)))


def parse_manual(album: str, artist: str, year: str, tracks_text: str,
                 track_count: int) -> ManualDetails | list[str]:
    """The details typed into the manual form, or what's wrong with them."""
    album, artist, year = album.strip(), artist.strip(), year.strip()
    titles = tuple(ln.strip() for ln in tracks_text.splitlines() if ln.strip())
    errors = []
    if not album:
        errors.append("Enter the album title.")
    if not artist:
        errors.append("Enter the artist.")
    if year and not re.fullmatch(r"\d{4}", year):
        errors.append("Enter the year as four digits, e.g. 1997, or leave it empty.")
    if len(titles) != track_count:
        errors.append(f"This CD has {track_count} tracks, but you entered {len(titles)} "
                      f"title{'s' if len(titles) != 1 else ''}. Enter one per line.")
    return errors or ManualDetails(album, artist, year, titles)
