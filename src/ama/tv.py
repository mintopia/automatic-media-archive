"""What a TV Disc looks like, and where its Episodes are filed.

A Disc *looks like TV* when, Play-alls aside, three or more Titles of episode length
are about as long as the longest, and that is well under a feature's length: two cuts
of a film, or a film and a long documentary, are not TV. Two such Titles *might be
TV*; Identification asks TMDB for a matching series. A TV Disc always goes to Review:
mapping Titles to Episodes needs a human (GLOSSARY).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import PurePosixPath

from ama import decoys, extras
from ama.archive import safe_name
from ama.discs import TitleRecord, TitleStatus
from ama.tmdb import DiscHints, Episode, Series, clean_term

TV = PurePosixPath("TV")
EPISODE_MIN_S = 15 * 60
EPISODE_MAX_S = decoys.MIN_FEATURE_S  # an Episode is shorter than a feature
MIN_EPISODES = 3  # fewer could be a film's cuts
SIMILAR = 0.8          # an episode is at least this fraction of the longest one
PLAY_ALL_SLACK_S = 90  # or 3%: a Play-all's length vs. the Titles it joins


def series_folder(series: Series) -> PurePosixPath:
    """`TV/Show (Year) {tmdb-ID}`."""
    return TV / f"{safe_name(series.title)} {{tmdb-{series.id}}}"


def season_folder(season: int) -> str:
    return f"Season {season:02d}"


def episode_path(series: Series, ep: Episode) -> PurePosixPath:
    """Where the Episode is filed, relative to the Archive root."""
    stem = f"{safe_name(series.name)} - s{ep.season:02d}e{ep.number:02d}"
    if ep.name:
        stem += f" - {safe_name(ep.name)}"
    return series_folder(series) / season_folder(ep.season) / f"{stem}.mkv"


def extra_path(series: Series, name: str) -> PurePosixPath:
    """A Title kept as an Extra of the show: `Other/<name>.mkv`, named and placed the way
    a film's Extras are (`extras.default_names`, `extras.plex_path`)."""
    return extras.plex_path(series_folder(series), name)


_SEASON_OR_DISC = re.compile(
    r"[\s:_-]*\b(?:season|series|s|disc|disk|d|vol|volume)\s*\d+\b.*$", re.I)


def series_terms(hints: DiscHints) -> list[str]:
    """Distinct series search terms from the Disc's names, season/disc numbers dropped."""
    out: list[str] = []
    for raw in (hints.bd_title, hints.disc_name, hints.volume_label, hints.volume_name):
        term = _SEASON_OR_DISC.sub("", clean_term(raw)).strip(" -–:")
        if term and term.casefold() not in {t.casefold() for t in out}:
            out.append(term)
    return out


def _ripped(titles: Iterable[TitleRecord]) -> list[TitleRecord]:
    return [t for t in titles if t.status == TitleStatus.RIPPED]


def _segments(segments_map: str) -> frozenset[str]:
    """MakeMKV's segment map ("1,2,3-5") as a set of segments."""
    out: set[str] = set()
    for part in (p.strip() for p in segments_map.split(",")):
        a, _, b = part.partition("-")
        if a.isdigit() and b.isdigit() and int(a) <= int(b):
            out.update(str(i) for i in range(int(a), int(b) + 1))
        elif part:
            out.add(part)
    return frozenset(out)


def play_alls(titles: Iterable[TitleRecord]) -> set[int]:
    """Numbers of the ripped Titles that are other Titles joined together."""
    ripped = _ripped(titles)
    found = set()
    for t in ripped:
        mine = _segments(t.segments)
        others = [o for o in ripped if o.number != t.number]
        inside = [o for o in others if (s := _segments(o.segments)) and s < mine]
        if len(inside) >= 2:
            found.add(t.number)
            continue
        if any(o.segments for o in others) and t.segments:
            continue  # the segment maps say it isn't
        shorter = [o for o in others if EPISODE_MIN_S <= o.duration_s < t.duration_s]
        total = sum(o.duration_s for o in shorter)
        if len(shorter) >= 2 and abs(total - t.duration_s) <= max(PLAY_ALL_SLACK_S,
                                                                  0.03 * t.duration_s):
            found.add(t.number)
    return found


def episode_like(titles: Iterable[TitleRecord]) -> list[TitleRecord]:
    """Ripped Titles that look like Episodes: long enough, about as long as the longest,
    not Play-alls. In Title order."""
    ripped = _ripped(titles)
    joined = play_alls(ripped)
    long = [t for t in ripped if t.number not in joined and t.duration_s >= EPISODE_MIN_S]
    if not long:
        return []
    longest = max(t.duration_s for t in long)
    return [t for t in long if t.duration_s >= SIMILAR * longest]


def _episode_shaped(titles: Iterable[TitleRecord]) -> list[TitleRecord]:
    like = episode_like(titles)
    return like if like and max(t.duration_s for t in like) < EPISODE_MAX_S else []


def looks_like_tv(titles: Iterable[TitleRecord]) -> bool:
    return len(_episode_shaped(titles)) >= MIN_EPISODES


def might_be_tv(titles: Iterable[TitleRecord]) -> bool:
    """Two Episode-shaped Titles: TV only if TMDB knows the series."""
    return len(_episode_shaped(titles)) >= 2
