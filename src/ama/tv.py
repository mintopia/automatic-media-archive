"""What a TV Disc looks like, and where its Episodes are archived.

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

from ama import decoys, extras, naming
from ama.jobs import TitleRecord, TitleStatus
from ama.naming import Pattern, Subject
from ama.tmdb import DiscHints, Episode, Series, clean_term

TV = PurePosixPath("TV")
EPISODE_MIN_S = 15 * 60
EPISODE_MAX_S = decoys.MIN_FEATURE_S  # an Episode is shorter than a feature
MIN_EPISODES = 3  # fewer could be a film's cuts
SIMILAR = 0.8          # an episode is at least this fraction of the longest one
PLAY_ALL_SLACK_S = 90  # or 3%: a Play-all's length vs. the Titles it joins


def series_folder(series: Series, pattern: Pattern = naming.default(Subject.TV)) -> PurePosixPath:
    """The show's folder, its TV Library `pattern`'s first: `TV/Show (Year) {tmdb-ID}` by
    default."""
    return TV / pattern.folders(_show_values(series), 1)


def season_path(series: Series, season: int,
                pattern: Pattern = naming.default(Subject.TV)) -> PurePosixPath:
    """The folder a season's Episodes go in by `pattern`, as far as it goes before any
    folder of an Episode's own: by default `TV/Show (Year) {tmdb-ID}/Season 01`."""
    depth = pattern.leading_folders(frozenset({"episode", "episode_title"}))
    return TV / pattern.folders(_show_values(series) | {"season": season}, depth)


def episode_path(series: Series, ep: Episode,
                 pattern: Pattern = naming.default(Subject.TV)) -> PurePosixPath:
    """Where the Episode is archived by its TV Library's `pattern`, relative to the Archive
    root; by default `TV/Show (Year) {tmdb-ID}/Season 01/Show - s01e02 - Episode Name.mkv`."""
    values = _show_values(series) | {"season": ep.season, "episode": ep.number,
                                     "episode_title": ep.name}
    return TV / pattern.render(values, ".mkv")


def _show_values(series: Series) -> dict[str, naming.Value]:
    return {"show": series.name, "year": series.year, "tmdb_id": series.id}


def extra_path(series: Series, name: str,
               pattern: Pattern = naming.default(Subject.TV)) -> PurePosixPath:
    """A Title kept as an Extra of the show: `Other/<name>.mkv` in the show's folder by
    `pattern`, named and placed the way a film's Extras are (`extras.default_names`,
    `extras.plex_path`)."""
    return extras.plex_path(series_folder(series, pattern), name)


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


def _disjoint(sets: Iterable[frozenset[str]]) -> int:
    """How many of `sets` (largest first) don't overlap those taken before them."""
    taken: set[str] = set()
    n = 0
    for s in sorted(sets, key=len, reverse=True):
        if not s & taken:
            taken |= s
            n += 1
    return n


def play_alls(titles: Iterable[TitleRecord]) -> set[int]:
    """Numbers of the ripped Titles that are other Titles joined together: two or more
    Titles that don't overlap each other inside it. (A DVD numbers cells afresh per title
    set, so two episodes can both look like `1-12` inside a pilot's `1-20`.)"""
    ripped = _ripped(titles)
    found = set()
    for t in ripped:
        mine = _segments(t.segments)
        others = [o for o in ripped if o.number != t.number]
        inside = [s for o in others if (s := _segments(o.segments)) and s < mine]
        if _disjoint(inside) >= 2:
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
