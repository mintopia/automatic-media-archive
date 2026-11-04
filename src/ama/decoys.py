"""Decoy playlist detection (#9), pure.

Some Blu-rays (and a few DVDs) hide the film among many decoy playlists: Titles
that run the same length as the film but play its scenes out of order. MakeMKV
can't tell them apart, so such a Disc always goes to Review, whatever TMDB says
(notes/research/makemkvcon.md §7).

Suspected decoys: at least MIN_VERSIONS Titles, each at least MIN_FEATURE_S
long, within DURATION_TOLERANCE_S of one another's length. Sizes and clips
aren't compared: a false alarm only costs a Review, a missed decoy files a
scrambled film. The likely film is the version whose segments (TINFO 26) run in
ascending order the most; with no order to go on, the lowest-numbered.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from ama.discs import TitleRecord

MIN_VERSIONS = 8
DURATION_TOLERANCE_S = 3
MIN_FEATURE_S = 10 * 60


@dataclass(frozen=True)
class Decoys:
    versions: tuple[TitleRecord, ...]  # the near-identical Titles, by number
    likely: TitleRecord                # the one that plays in order, most likely the film
    confident: bool                    # it plays in order more than every other version


def segments(segments_map: str) -> tuple[int, ...]:
    """MakeMKV's segment map ("1-3,7") as clip numbers; () if it can't be read."""
    out: list[int] = []
    try:
        for part in filter(None, segments_map.split(",")):
            lo, _, hi = part.strip().partition("-")
            out.extend(range(int(lo), int(hi or lo) + 1))
    except ValueError:
        return ()
    return tuple(out)


def in_order(t: TitleRecord) -> int:
    """How many of the Title's segment steps go forwards."""
    s = segments(t.segments)
    return sum(b > a for a, b in zip(s, s[1:]))


def detect(titles: Iterable[TitleRecord]) -> Decoys | None:
    long = sorted((t for t in titles if t.duration_s >= MIN_FEATURE_S), key=lambda t: t.number)
    best: list[TitleRecord] = []
    for anchor in long:
        group = [t for t in long
                 if abs(t.duration_s - anchor.duration_s) <= DURATION_TOLERANCE_S]
        if len(group) > len(best):
            best = group
    if len(best) < MIN_VERSIONS:
        return None
    ranked = sorted(best, key=lambda t: (-in_order(t), t.number))
    confident = in_order(ranked[0]) > in_order(ranked[1])
    return Decoys(tuple(best), ranked[0], confident)
