"""The Review queue as the UI lists it: one row per Job, saying why it needs a human.

A Disc Type with its own Review adds a branch to `review_items` (and its
ReviewReasons to `_GENERIC`, used when there is nothing more specific to say).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastapi import Request
from fastapi.responses import RedirectResponse

from ama import cdreview, decoys, review, tvreview
from ama.cyanrip import ArStatus
from ama.jobs import JobRecord, ReviewReason, TitleStatus
from ama.drive import DiscType

if TYPE_CHECKING:
    from ama.app import Services


@dataclass(frozen=True)
class ReviewItem:
    record: JobRecord
    title: str
    summary: str  # why it's here, e.g. "3 editions match this CD · pick yours"
    action: str   # the button, e.g. "Choose edition"
    offer_tv: bool = False  # a film Review that may really be episodes: offer "It's TV episodes"

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
    ReviewReason.PICK_RUNTIME_MISMATCH: ("The running time of the film you picked doesn't "
                                         "match the Disc · confirm the film", "Confirm film"),
    ReviewReason.PICK_NOT_FITTING: ("The edition you picked doesn't fit this CD · pick yours",
                                    "Choose edition"),
}


def reason_summary(reason: ReviewReason) -> str:
    """Why a Disc needs Review, in a line (no more specific than its reason)."""
    return _GENERIC[reason][0]


def review_items(services: Services) -> list[ReviewItem]:
    items = []
    for rec in review.queue(services.jobs):
        if rec.disc_type == DiscType.CD:
            items.append(_cd_item(services, rec))
        else:
            items.append(_video_item(services, rec))
    return items


FILM_UNSURE = frozenset({ReviewReason.NO_MATCH, ReviewReason.RUNTIME_MISMATCH,
                          ReviewReason.MULTIPLE_MATCHES, ReviewReason.PICK_RUNTIME_MISMATCH})


def _video_item(services: Services, rec: JobRecord) -> ReviewItem:
    tv = tvreview.wants_tv(rec)
    reason = ReviewReason.EPISODES if tv else rec.review_reason or ReviewReason.NO_MATCH
    summary, action = _GENERIC[reason]
    if reason == ReviewReason.DECOY_PLAYLISTS and (
            found := decoys.detect(t for t in rec.titles if t.status == TitleStatus.RIPPED)):
        summary = (f"{len(found.versions)} near-identical versions of the film "
                   "(a copy-protection trick) · check which is right")
    if guess := (services.series_guesses if tv else services.film_guesses).get(rec.id):
        summary = f"Best guess {guess.name} · {summary}"
    return ReviewItem(rec, rec.name, summary, action, offer_tv=reason in FILM_UNSURE)


def cd_title(services: Services, rec: JobRecord) -> str:
    """A CD in Review by the release picked while it ripped, else its first matching edition,
    else its label."""
    cd = services.cd.job(rec.id)
    if cd.pick:
        return cd.pick.name
    editions = cdreview.candidates(rec.scratch_dir, cd.tracks)
    return (f"{editions[0].release.title} — {editions[0].release.artist}" if editions
            else rec.label or "Unknown CD")


def _cd_item(services: Services, rec: JobRecord) -> ReviewItem:
    tracks = services.cd.job(rec.id).tracks
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


def after_decision(request: Request, job_id: int, headline: str, detail: str) -> RedirectResponse:
    """Go on to the next Disc in Review (else the queue), saying what happens to this one."""
    notes = _notes(request)
    notes.pop(job_id, None)
    notes[job_id] = (headline, detail)
    while len(notes) > _NOTES_KEPT:
        notes.pop(next(iter(notes)))
    services = request.app.state.services
    nxt = next((r for r in review.queue(services.jobs) if r.id != job_id), None)
    page = f"/review/{nxt.id}" if nxt else "/review"
    return RedirectResponse(f"{page}?done={job_id}", status_code=303)


def done_note(request: Request) -> tuple[str, str] | None:
    """The note `after_decision` left for `?done=<Job id>`, if any."""
    raw = request.query_params.get("done", "")
    return _notes(request).get(int(raw)) if raw.isdigit() else None
