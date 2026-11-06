"""TV Review: mapping a Disc's ripped Titles to Episodes.

A video Disc in Review is TV when it looked like TV at Identification
(`ReviewReason.EPISODES`), or when the user marked it so (`mark`, saved to
scratch `tv.json`; marking it a film again sends it back to the Movie Review).
A mark made while the Disc rips decides Identification: TV goes to TV Review,
a film is never taken for TV.

Each ripped Title gets a *choice*: an Episode code (`S01E04`, from the series'
seasons on TMDB, specials are season 0), `extra` (kept, filed to the show's
`Other/`) or `discard` (not Encoded). `suggest` pre-fills them: episode-length
Titles get the season's Episodes in Title order, Play-alls are discarded and
anything else is kept as an Extra.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from ama.jobs import JobRecord, ReviewReason, TitleRecord
from ama.tmdb import Episode
from ama.tv import episode_like, play_alls

MARK_FILE = "tv.json"
EXTRA = "extra"
DISCARD = "discard"


def marked(rec: JobRecord) -> bool | None:
    """The user's mark: True for TV, False for a film, None if they haven't said."""
    try:
        kind = json.loads((rec.scratch_dir / MARK_FILE).read_text(encoding="utf-8"))["kind"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return kind == "tv"


def wants_tv(rec: JobRecord) -> bool:
    mark = marked(rec)
    return rec.review_reason == ReviewReason.EPISODES if mark is None else mark


def mark(rec: JobRecord, tv: bool) -> None:
    """The user says the Disc is TV (or a film after all)."""
    tmp = rec.scratch_dir / f"{MARK_FILE}.tmp"
    tmp.write_text(json.dumps({"kind": "tv" if tv else "film"}), encoding="utf-8")
    tmp.replace(rec.scratch_dir / MARK_FILE)


def suggest(titles: Iterable[TitleRecord], episodes: list[Episode]) -> dict[int, str]:
    """A first guess at each ripped Title's choice."""
    titles = list(titles)
    joined = play_alls(titles)
    like = {t.number for t in episode_like(titles)}
    left = iter(episodes)
    out: dict[int, str] = {}
    for t in sorted(titles, key=lambda t: t.number):
        if t.number in joined:
            out[t.number] = DISCARD
        elif t.number in like and (ep := next(left, None)) is not None:
            out[t.number] = ep.code
        else:
            out[t.number] = EXTRA
    return out


@dataclass(frozen=True)
class Kept:
    """A Title the user keeps: as `episode`, or as an Extra (None)."""

    title: TitleRecord
    episode: Episode | None


def decide(titles: Iterable[TitleRecord], choices: Mapping[int, str],
           episodes: Mapping[str, Episode]) -> tuple[list[Kept], list[str]]:
    """The Titles kept, or what's wrong with the choices (`episodes`: by code)."""
    kept: list[Kept] = []
    errors: list[str] = []
    used: dict[str, int] = {}
    for t in sorted(titles, key=lambda t: t.number):
        choice = choices.get(t.number, "")
        if choice == DISCARD:
            continue
        if choice == EXTRA:
            kept.append(Kept(t, None))
            continue
        ep = episodes.get(choice)
        if ep is None:
            errors.append(f"Title {t.number}: pick an Episode, Extra or Discard")
        elif ep.code in used:
            errors.append(f"Titles {used[ep.code]} and {t.number} are both {ep.code}: "
                          "each Episode can be only one Title")
        else:
            used[ep.code] = t.number
            kept.append(Kept(t, ep))
    if not errors and not any(k.episode for k in kept):
        errors.append("Map at least one Title to an Episode (or mark the Disc as a film)")
    return kept, errors


def season_of(code: str) -> int | None:
    """The season in an Episode code ("S01E04" -> 1), None if it isn't one."""
    if len(code) >= 6 and code[0] == "S" and "E" in code:
        s = code[1:code.index("E")]
        return int(s) if s.isdigit() else None
    return None
