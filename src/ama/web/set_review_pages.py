"""Set Review (#14): "Is this Disc part of a set?", asked before a video Disc's Review.

`GET /review/{id}` shows it (dispatched from review_pages) while the question is
unanswered and a filed set's name matches the Disc's names; `GET /review/{id}/set`
shows it any time, offering every filed set of the Disc's kind (TV seasons for a TV
Disc, films otherwise). `POST /review/{id}/set`:

- `part=no`: the Disc is identified on its own (its normal Review page next).
- `part=yes&set=<key>&disc=N`, TV: recorded, then the Episode mapping, which starts at
  the set's series and season and carries on after the earlier Discs' Episodes.
- the same for a film: a bonus Disc. Every ripped Title is queued as an Extra of the
  film (`tv_titles`, filed by the TvArchiver into `<film folder>/Other/`) and the Disc
  leaves Review.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from ama import review, sets, tvreview
from ama.discs import DiscRecord, DiscStatus
from ama.moviearchive import TOPIC as ENCODE_TOPIC
from ama.moviereview import ripped_titles
from ama.sets import Answer, DiscSet, Library, SetKey
from ama.tmdb import load_hints, search_terms
from ama.tv import series_terms
from ama.video_rip import VIDEO_DISC_TYPES
from ama.web import TEMPLATES, view_context

router = APIRouter()


def _services(request: Request):
    return request.app.state.services


def library_of(rec: DiscRecord) -> Library:
    return Library.TV if tvreview.wants_tv(rec) else Library.MOVIE


def offered(services, rec: DiscRecord, everything: bool = False) -> list[DiscSet]:
    """Filed sets the Disc could belong to: those named like it (then, with `everything`,
    the rest)."""
    library = library_of(rec)
    filed = services.sets.filed(library)
    terms = (series_terms if library == Library.TV else search_terms)(
        load_hints(rec.scratch_dir, rec.label))
    named = sets.matching(filed, terms)
    return named + [s for s in filed if s not in named] if everything else named


def pending(services, rec: DiscRecord) -> bool:
    """Ask the question first: not answered yet, and a set is named like the Disc."""
    return sets.answer(rec) is None and bool(offered(services, rec))


def page(request: Request, services, rec: DiscRecord, everything: bool = False,
         errors: list[str] | None = None, status_code: int = 200,
         form: dict[str, str] | None = None) -> Response:
    offer = offered(services, rec, everything)
    ans = sets.answer(rec)
    first = offer[0] if offer else None
    form = form or {}
    picked = form.get("set") or (str(ans.key) if ans and ans.key else str(first.key) if first
                                 else "")
    chosen = next((s for s in offer if str(s.key) == picked), first)
    ctx = view_context(services) | {
        "current": "/review", "record": rec, "tv": library_of(rec) == Library.TV,
        "titles": len(ripped_titles(rec)), "sets": offer, "picked": picked,
        "part": form.get("part") or ("no" if (ans and not ans.key) or not offer else "yes"),
        "disc": form.get("disc") or (ans.number if ans and ans.key else
                                     chosen.next_number if chosen else 1),
        "errors": errors or [],
    }
    return TEMPLATES.TemplateResponse(request, "review_set.html", ctx, status_code=status_code)


def _video_in_review(services, disc_id: int) -> DiscRecord | None:
    rec = services.discs.get(disc_id)
    if rec is None or rec.disc_type not in VIDEO_DISC_TYPES:
        raise HTTPException(404, "No such video Disc")
    return rec if rec.status == DiscStatus.REVIEW else None


@router.get("/review/{disc_id}/set")
def ask(request: Request, disc_id: int) -> Response:
    services = _services(request)
    rec = _video_in_review(services, disc_id)
    if rec is None:
        return RedirectResponse(f"/discs/{disc_id}", status_code=303)
    return page(request, services, rec, everything=True)


@router.post("/review/{disc_id}/set")
def answer(request: Request, disc_id: int, part: Annotated[str, Form()] = "",
           set_: Annotated[str, Form(alias="set")] = "", disc: Annotated[str, Form()] = "") -> Response:
    services = _services(request)
    rec = _video_in_review(services, disc_id)
    if rec is None:
        return RedirectResponse("/review", status_code=303)
    if part == "no":
        sets.save_answer(rec, Answer(None))
        services.sets.detach(rec.id)
        services.discs.log(rec.id, "Review: not part of a set")
        return RedirectResponse(f"/review/{rec.id}", status_code=303)
    if part != "yes":
        raise HTTPException(400, "part is yes or no")
    key = SetKey.parse(set_)
    chosen = services.sets.find(key) if key and key.library == library_of(rec) else None
    number = int(disc) if disc.strip().isdigit() else 0
    errors = []
    if chosen is None:
        errors.append("Pick the set this Disc belongs to")
    elif number < 1:
        errors.append("Enter which Disc of the set this is (1 or more)")
    elif number in chosen.numbers:
        errors.append(f"Disc {number} of {chosen.name} is already filed: "
                      "check the number on the Disc")
    if errors:
        return page(request, services, rec, everything=True, errors=errors, status_code=400,
                    form={"part": part, "set": set_, "disc": disc})
    assert chosen is not None
    sets.save_answer(rec, Answer(chosen.key, number))
    services.sets.attach(rec.id, chosen.key, number)
    services.discs.log(rec.id, f"Review: Disc {number} of the set {chosen.name}")
    if chosen.key.library == Library.TV:
        return RedirectResponse(f"/review/{rec.id}", status_code=303)
    _file_as_bonus(services, rec, chosen)
    return RedirectResponse("/review", status_code=303)


def _file_as_bonus(services, rec: DiscRecord, film_set: DiscSet) -> None:
    """Queue every ripped Title as an Extra of the film and hand the Disc back."""
    titles = ripped_titles(rec)
    services.tv_archive.titles.enqueue(
        rec.id, film_set.show,
        [(t.number, None, sets.bonus_path(film_set, rec.label, t.number)) for t in titles])
    if services.discs.requeue(rec.id):
        services.discs.log(rec.id, f"Queued {len(titles)} Title{'s' if len(titles) != 1 else ''}"
                                   f" for Encode as Extras of {film_set.name}")
        for topic in (review.TOPIC, "rip", ENCODE_TOPIC):
            services.bus.publish(topic)
