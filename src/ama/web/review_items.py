"""The Review queue as the UI lists it: one row per Disc, saying why it needs a human.

A Disc Type with its own Review adds a branch to `review_items` (and its
ReviewReasons to `_GENERIC`, used when there is nothing more specific to say).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastapi import Request
from fastapi.responses import RedirectResponse

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
    ReviewReason.NO_RELEASE: ("Not in the music database (MusicBrainz) · enter the details",
                              "Enter details"),
    ReviewReason.NOT_ACCURATE: ("Some tracks didn't match the online check · "
                                "keep it or rip again", "Check tracks"),
    ReviewReason.NOT_IN_ACCURATERIP: ("Not in the online check, so it couldn't be verified · "
                                      "keep it or rip again", "Check Rip"),
    ReviewReason.ACCURATERIP_UNAVAILABLE: ("The online check couldn't be reached · "
                                           "keep it or rip again", "Check Rip"),
    # video
    ReviewReason.NO_MATCH: ("Not in the film database (TMDB) · identify the film", "Identify"),
    ReviewReason.RUNTIME_MISMATCH: ("Found in the film database, but the running time doesn't "
                                    "match · confirm the film", "Confirm film"),
    ReviewReason.MULTIPLE_MATCHES: ("Several films match · pick yours", "Choose film"),
    ReviewReason.EPISODES: ("Looks like TV episodes · match each Title to an Episode",
                            "Match episodes"),
    ReviewReason.DECOY_PLAYLISTS: ("Several near-identical versions of the film · check which "
                                   "Title is the film", "Choose Title"),
}


def reason_summary(reason: ReviewReason) -> str:
    """Why a Disc needs Review, in a line (no more specific than its reason)."""
    return _GENERIC[reason][0]


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
        summary = (f"{len(found.versions)} near-identical versions of the film "
                   "(a copy-protection trick) · check which is right")
    return ReviewItem(rec, rec.name, summary, action)


def cd_title(services: Services, rec: DiscRecord) -> str:
    """A CD in Review by its first matching edition, else its label."""
    editions = cdreview.candidates(rec.scratch_dir, services.cd.disc(rec.id).tracks)
    return (f"{editions[0].release.title} — {editions[0].release.artist}" if editions
            else rec.label or "Unknown CD")


def _cd_item(services: Services, rec: DiscRecord) -> ReviewItem:
    tracks = services.cd.disc(rec.id).tracks
    editions = cdreview.candidates(rec.scratch_dir, tracks)
    title = cd_title(services, rec)
    summary, action = _GENERIC[rec.review_reason or ReviewReason.NO_RELEASE]
    match rec.review_reason:
        case ReviewReason.MULTIPLE_RELEASES:
            summary = f"{len(editions)} editions match this CD · pick yours"
        case ReviewReason.NOT_ACCURATE:
            bad = len(cdreview.unverified(tracks, ArStatus.MISMATCH))
            summary = (f"{plural(bad, 'track')} didn't match the online check · "
                       "keep it or rip again")
    return ReviewItem(rec, title, summary, action)


_NOTES_KEPT = 20


def _notes(request: Request) -> dict[int, tuple[str, str]]:
    state = request.app.state
    if not hasattr(state, "review_notes"):
        state.review_notes = {}
    return state.review_notes


def after_decision(request: Request, disc_id: int, headline: str, detail: str) -> RedirectResponse:
    """Go on to the next Disc in Review (else the queue), saying what happens to this one."""
    notes = _notes(request)
    notes.pop(disc_id, None)
    notes[disc_id] = (headline, detail)
    while len(notes) > _NOTES_KEPT:
        notes.pop(next(iter(notes)))
    services = request.app.state.services
    nxt = next((r for r in review.queue(services.discs) if r.id != disc_id), None)
    page = f"/review/{nxt.id}" if nxt else "/review"
    return RedirectResponse(f"{page}?done={disc_id}", status_code=303)


def done_note(request: Request) -> tuple[str, str] | None:
    """The note `after_decision` left for `?done=<disc id>`, if any."""
    raw = request.query_params.get("done", "")
    return _notes(request).get(int(raw)) if raw.isdigit() else None
