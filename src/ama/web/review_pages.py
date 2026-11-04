"""Review routes: the queue, and each Disc's Review page and decisions.

Each Disc Type has its own page and decision routes (CD here). A decision is
saved, the Disc goes back to `ripped` and its worker files it; a decision on a
Disc that is no longer in Review is ignored (double submit, second tab).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from ama import cdreview, review, tvreview
from ama.cyanrip import ArStatus
from ama.discs import DiscRecord, DiscStatus, Failure, FailureKind, ReviewReason
from ama.drive import DiscType
from ama.musicbrainz import Match
from ama.video_rip import VIDEO_DISC_TYPES
from ama.web import TEMPLATES, extras_pages, movie_review_pages, set_review_pages, \
    tv_review_pages, view_context
from ama.web.review_items import plural

router = APIRouter()

DISCARDED = Failure(FailureKind.DISCARDED, "You discarded this Rip in Review.",
                    "Insert the Disc again to rip it from the start.")

# MusicBrainz release countries as people say them (others are shown as the code).
COUNTRIES = {"GB": "UK", "US": "US", "JP": "Japan", "DE": "Germany", "FR": "France",
             "XE": "Europe", "XW": "Worldwide", "CA": "Canada", "AU": "Australia",
             "NL": "Netherlands", "IT": "Italy", "ES": "Spain", "KR": "South Korea",
             "SE": "Sweden", "XU": "Unknown country"}


def _services(request: Request):
    return request.app.state.services


def _in_review(services, disc_id: int) -> DiscRecord | None:
    rec = services.discs.get(disc_id)
    if rec is None:
        raise HTTPException(404, "No such Disc")
    return rec if rec.status == DiscStatus.REVIEW else None


def _decided(services, rec: DiscRecord) -> Response:
    if services.discs.requeue(rec.id):
        _publish(services)
    return RedirectResponse("/review", status_code=303)


def _publish(services) -> None:
    for topic in (review.TOPIC, "rip"):
        services.bus.publish(topic)


@router.get("/review", response_class=HTMLResponse)
def queue(request: Request) -> Response:
    services = _services(request)
    ctx = view_context(services) | {"current": "/review",
                                    "extras_to_sort": extras_pages.to_sort(services)}
    return TEMPLATES.TemplateResponse(request, "review.html", ctx)


@router.get("/review/{disc_id}", response_class=HTMLResponse)
def review_page(request: Request, disc_id: int) -> Response:
    services = _services(request)
    rec = _in_review(services, disc_id)
    if rec is None:
        return RedirectResponse(f"/discs/{disc_id}", status_code=303)
    if rec.disc_type == DiscType.CD:
        return _cd_page(request, services, rec)
    if rec.disc_type in VIDEO_DISC_TYPES and set_review_pages.pending(services, rec):
        return set_review_pages.page(request, services, rec)
    if rec.disc_type in VIDEO_DISC_TYPES and tvreview.wants_tv(rec):
        return tv_review_pages.page(request, services, rec)
    if rec.disc_type in VIDEO_DISC_TYPES:
        return movie_review_pages.page(request, services, rec)
    raise HTTPException(404, "This Disc Type has no Review page yet")


# ---- CD ------------------------------------------------------------------------

@dataclass(frozen=True)
class Edition:
    """One release offered on the CD Review page, with what tells it apart."""

    match: Match
    heading: str               # e.g. "Parlophone · UK · 1997"
    facts: tuple[tuple[str, str], ...]

    @property
    def value(self) -> str:
        return f"{self.match.release.id}:{self.match.disc_number}"


def _edition(m: Match, show_title: bool) -> Edition:
    r = m.release
    labels = list(dict.fromkeys(name for name, _ in r.labels if name))
    parts = [*labels[:1], COUNTRIES.get(r.country, r.country) if r.country else None, r.date,
             r.status if r.status and r.status != "Official" else None]
    heading = " · ".join(p for p in parts if p) or "No release details"
    cats = list(dict.fromkeys(cat for _, cat in r.labels if cat))
    facts = [("Title", r.title)] if show_title else []
    facts += [("Catalogue no.", ", ".join(cats))] if cats else []
    facts += [("Barcode", r.barcode)] if r.barcode else []
    if r.disc_total > 1:
        facts.append(("Discs", f"{r.disc_total} CDs · this is disc {m.disc_number}"))
    facts.append(("Tracks", str(len(m.tracks))))
    return Edition(m, heading, tuple(facts))


def _join(numbers: list[int]) -> str:
    s = [str(n) for n in numbers]
    return s[0] if len(s) == 1 else f"{', '.join(s[:-1])} and {s[-1]}"


def _ar_notice(reason: ReviewReason | None, tracks) -> tuple[str, str] | None:
    """(headline, explanation) when the Rip itself needs accepting, else None."""
    match reason:
        case ReviewReason.NOT_ACCURATE:
            bad = cdreview.unverified(tracks, ArStatus.MISMATCH)
            which = f"Tracks {_join(bad)} don't" if len(bad) > 1 else f"Track {_join(bad)} doesn't"
            return (f"{plural(len(bad), 'track')} couldn't be verified",
                    f"{which} match the online check (AccurateRip). They may play fine, "
                    "or the CD may be scratched.")
        case ReviewReason.NOT_IN_ACCURATERIP:
            return ("This Rip can't be verified",
                    "This CD isn't in the online check (AccurateRip) yet, so the Rip can't be "
                    "compared with anyone else's. It's usually fine.")
        case ReviewReason.ACCURATERIP_UNAVAILABLE:
            return ("This Rip couldn't be verified",
                    "The online check (AccurateRip) couldn't be reached during the Rip. "
                    "It's usually fine; re-rip it later if you want it checked.")
    return None


def _length(seconds: float) -> str:
    s = round(seconds)
    return f"{s // 60} min {s % 60} s"


def _when(at: datetime | None) -> str:
    if at is None:
        return ""
    return f"Today, {at:%H:%M}" if at.date() == date.today() else f"{at:%d %b %Y, %H:%M}"


def _cd_page(request: Request, services, rec: DiscRecord, form: dict[str, str] | None = None,
             errors: list[str] | None = None, status_code: int = 200) -> Response:
    tracks = services.cd.disc(rec.id).tracks
    matches = cdreview.candidates(rec.scratch_dir, tracks)
    titles_differ = len({m.release.title for m in matches}) > 1
    editions = [_edition(m, titles_differ) for m in matches]
    first = matches[0] if matches else None
    if form is None:
        form = {"album": first.release.title if first else "",
                "artist": first.release.artist if first else "",
                "year": (first.release.date or "")[:4] if first else "",
                "tracks": "\n".join(t.title for t in first.tracks) if first else ""}
    if len(matches) > 1:
        heading = f"Which edition of {first.release.title} is this?"
        sub = (f"{len(matches)} editions match this CD. Check the back of the case and pick "
               "the one that matches.")
    elif first:
        heading = f"{first.release.title} — {first.release.artist}"
        sub = "One edition matches this CD. Check the Rip, then file it."
    else:
        heading = "What is this CD?"
        sub = ("The music database (MusicBrainz) doesn't know this CD. Enter its details "
               "and it's filed like any other.")
    disc_id = cdreview.disc_id(rec.scratch_dir)
    ctx = view_context(services) | {
        "current": "/review", "record": rec, "heading": heading, "sub": sub,
        "editions": editions, "notice": _ar_notice(rec.review_reason, tracks),
        "form": form, "errors": errors or [], "manual_open": not editions or bool(errors),
        "track_count": len(cdreview.audio_tracks(tracks)),
        "length": _length(sum(t.seconds for t in tracks)),
        "disc_id": disc_id, "ripped_at": _when(rec.finished_at),
    }
    return TEMPLATES.TemplateResponse(request, "review_cd.html", ctx, status_code=status_code)


def _cd_in_review(services, disc_id: int) -> DiscRecord | None:
    rec = _in_review(services, disc_id)
    if rec is not None and rec.disc_type != DiscType.CD:
        raise HTTPException(404, "Not a CD")
    return rec


@router.post("/review/{disc_id}/release")
def pick_release(request: Request, disc_id: int,
                 release: Annotated[str, Form()] = "") -> Response:
    services = _services(request)
    rec = _cd_in_review(services, disc_id)
    if rec is None:
        return RedirectResponse("/review", status_code=303)
    tracks = services.cd.disc(rec.id).tracks
    picked = next((m for m in cdreview.candidates(rec.scratch_dir, tracks)
                   if f"{m.release.id}:{m.disc_number}" == release), None)
    if picked is None:
        raise HTTPException(400, "That edition isn't one of the matches for this CD")
    cdreview.save_decision(rec.scratch_dir,
                           cdreview.PickRelease(picked.release.id, picked.disc_number))
    services.discs.log(rec.id, f"Review: picked {picked.release.title} by "
                               f"{picked.release.artist} (MusicBrainz release "
                               f"{picked.release.id}, disc {picked.disc_number})")
    return _decided(services, rec)


@router.post("/review/{disc_id}/manual", response_class=HTMLResponse)
def manual(request: Request, disc_id: int, album: Annotated[str, Form()] = "",
           artist: Annotated[str, Form()] = "", year: Annotated[str, Form()] = "",
           tracks: Annotated[str, Form()] = "") -> Response:
    services = _services(request)
    rec = _cd_in_review(services, disc_id)
    if rec is None:
        return RedirectResponse("/review", status_code=303)
    count = len(cdreview.audio_tracks(services.cd.disc(rec.id).tracks))
    details = cdreview.parse_manual(album, artist, year, tracks, count)
    if isinstance(details, list):
        form = {"album": album, "artist": artist, "year": year, "tracks": tracks}
        return _cd_page(request, services, rec, form, details, status_code=400)
    cdreview.save_decision(rec.scratch_dir, details)
    services.discs.log(rec.id, f"Review: details entered by hand: {details.album} by "
                               f"{details.artist}")
    return _decided(services, rec)


@router.post("/review/{disc_id}/accept")
def accept(request: Request, disc_id: int) -> Response:
    services = _services(request)
    rec = _cd_in_review(services, disc_id)
    if rec is None:
        return RedirectResponse("/review", status_code=303)
    cdreview.save_decision(rec.scratch_dir, cdreview.AcceptRip())
    services.discs.log(rec.id, "Review: Rip accepted although AccurateRip didn't verify "
                               "every track")
    return _decided(services, rec)


@router.post("/review/{disc_id}/discard")
def discard(request: Request, disc_id: int) -> Response:
    services = _services(request)
    rec = _cd_in_review(services, disc_id)
    if rec is not None:
        services.discs.log(rec.id, "Review: Rip discarded; scratch deleted")
        services.discs.mark_failed(rec.id, DISCARDED)
        services.discs.dismiss(rec.id)
        _publish(services)
    return RedirectResponse("/review", status_code=303)
