"""Decoy playlist detection, pure.

Some Blu-rays hide the film among many decoy playlists: versions of one feature that
run its length and play the same clips out of order (notes/research/makemkvcon.md
§7). Sizes aren't compared: a false alarm only costs a Review, a missed decoy files a
scrambled film. Episodes differ from decoys by being shorter than a feature and made
of their own clips.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from ama.discs import TitleRecord

MIN_VERSIONS = 8
DURATION_TOLERANCE_S = 3
MIN_FEATURE_S = 70 * 60  # shorter is an Episode or an Extra, not a version of the film
SHARED_CLIPS = 0.5  # a version plays at least this share of the other versions' clips


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


def _same_clips(a: TitleRecord, b: TitleRecord) -> bool:
    """Whether two Titles play mostly the same clips (true when either map is unknown)."""
    sa, sb = set(segments(a.segments)), set(segments(b.segments))
    if not sa or not sb:
        return True
    return len(sa & sb) >= SHARED_CLIPS * min(len(sa), len(sb))


def detect(titles: Iterable[TitleRecord]) -> Decoys | None:
    long = sorted((t for t in titles if t.duration_s >= MIN_FEATURE_S), key=lambda t: t.number)
    best: list[TitleRecord] = []
    for anchor in long:
        group = [t for t in long
                 if abs(t.duration_s - anchor.duration_s) <= DURATION_TOLERANCE_S
                 and _same_clips(t, anchor)]
        if len(group) > len(best):
            best = group
    if len(best) < MIN_VERSIONS:
        return None
    ranked = sorted(best, key=lambda t: (-in_order(t), t.number))
    confident = in_order(ranked[0]) > in_order(ranked[1])
    return Decoys(tuple(best), ranked[0], confident)
