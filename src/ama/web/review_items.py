"""The Review queue as the UI lists it: one row per Disc, saying why it needs a human.

A Disc Type with its own Review adds a branch to `review_items` (and its
ReviewReasons to `_GENERIC`, used when there is nothing more specific to say).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ama import cdreview, decoys, review
from ama.cyanrip import ArStatus
from ama.discs import DiscRecord, ReviewReason, TitleStatus
from ama.drive import DiscType

if TYPE_CHECKING:
    from ama.app import Services


@dataclass(frozen=True)
class ReviewItem:
    record: DiscRecord
    title: str
    summary: str  # why it's here, e.g. "3 editions match this CD · pick yours"
    action: str   # the button, e.g. "Choose edition"

    @property
    def href(self) -> str:
        return f"/review/{self.record.id}"


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


_GENERIC: dict[ReviewReason, tuple[str, str]] = {
    ReviewReason.MULTIPLE_RELEASES: ("Several editions match · pick yours", "Choose edition"),
    ReviewReason.NO_RELEASE: ("Not found on MusicBrainz · enter the details", "Enter details"),
    ReviewReason.NOT_ACCURATE: ("Some tracks didn't match the online check · accept or discard",
                                "Check tracks"),
    ReviewReason.NOT_IN_ACCURATERIP: ("Not in the online check, so it couldn't be verified · "
                                      "accept or discard", "Check Rip"),
    ReviewReason.ACCURATERIP_UNAVAILABLE: ("The online check couldn't be reached · "
                                           "accept or discard", "Check Rip"),
    # video (#6; the Movie Review page itself is #7)
    ReviewReason.NO_MATCH: ("Not found on TMDB · identify the film", "Identify"),
    ReviewReason.RUNTIME_MISMATCH: ("Found on TMDB, but the running time doesn't match · "
                                    "confirm the film", "Confirm film"),
    ReviewReason.MULTIPLE_MATCHES: ("Several films match · pick yours", "Choose film"),
    ReviewReason.EPISODES: ("Looks like TV episodes · match each Title to an Episode",
                            "Match episodes"),
    ReviewReason.DECOY_PLAYLISTS: ("Suspected decoy playlists · check which Title is the film",
                                   "Choose Title"),
}


def review_items(services: Services) -> list[ReviewItem]:
    items = []
    for rec in review.queue(services.discs):
        if rec.disc_type == DiscType.CD:
            items.append(_cd_item(services, rec))
        else:
            items.append(_video_item(rec))
    return items


def _video_item(rec: DiscRecord) -> ReviewItem:
    summary, action = _GENERIC[rec.review_reason or ReviewReason.NO_RELEASE]
    if rec.review_reason == ReviewReason.DECOY_PLAYLISTS and (
            found := decoys.detect(t for t in rec.titles if t.status == TitleStatus.RIPPED)):
        summary = (f"Suspected decoy playlists · {len(found.versions)} near-identical versions "
                   "of the film · check which is right")
    return ReviewItem(rec, rec.name, summary, action)


def _cd_item(services: Services, rec: DiscRecord) -> ReviewItem:
    tracks = services.cd.disc(rec.id).tracks
    editions = cdreview.candidates(rec.scratch_dir, tracks)
    title = (f"{editions[0].release.title} — {editions[0].release.artist}" if editions
             else rec.label or "Unknown CD")
    summary, action = _GENERIC[rec.review_reason or ReviewReason.NO_RELEASE]
    match rec.review_reason:
        case ReviewReason.MULTIPLE_RELEASES:
            summary = f"{len(editions)} editions match this CD · pick yours"
        case ReviewReason.NOT_ACCURATE:
            bad = len(cdreview.unverified(tracks, ArStatus.MISMATCH))
            summary = f"{plural(bad, 'track')} didn't match the online check · accept or discard"
    return ReviewItem(rec, title, summary, action)
