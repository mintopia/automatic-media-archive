"""Set Review: "Is this Disc part of a set?", asked before a video Disc's Review.

`GET /review/{id}` shows it (dispatched from review_pages) while the question is
unanswered and an archived set's name matches the Disc's names; `GET /review/{id}/set`
shows it any time, offering every archived set of the Disc's kind (TV seasons for a TV
Disc, films otherwise). `POST /review/{id}/set`:

- `part=no`: the Disc is identified on its own (its normal Review page next).
- `part=yes&set=<key>&disc=N`, TV: recorded, then the Episode mapping, which starts at
  the set's series and season and carries on after the earlier Discs' Episodes.
- the same for a film: an Extras Disc. Every ripped Title is queued as an Extra of the
  film (`tv_titles`, archived by the TvArchiver into `<film folder>/Other/`) and the Disc
  leaves Review.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from ama import sets, tvreview
from ama.jobs import JobRecord, JobStatus
from ama.moviereview import ripped_titles
from ama.sets import Answer, DiscSet, SetKind, SetKey
from ama.tmdb import load_hints, search_terms
from ama.tv import series_terms
from ama.video_rip import VIDEO_DISC_TYPES
from ama.web import TEMPLATES, view_context
from ama.web.review_items import after_decision, done_note
from ama.events import Topic

router = APIRouter()


def _services(request: Request):
    return request.app.state.services


def kind_of(rec: JobRecord) -> SetKind:
    return SetKind.TV if tvreview.wants_tv(rec) else SetKind.MOVIE


def offered(services, rec: JobRecord, everything: bool = False) -> list[DiscSet]:
    """Archived sets the Disc could belong to: those named like it (then, with `everything`,
    the rest)."""
    kind = kind_of(rec)
    archived = services.sets.archived(kind)
    terms = (series_terms if kind == SetKind.TV else search_terms)(
        load_hints(rec.scratch_dir, rec.label))
    named = sets.matching(archived, terms)
    return named + [s for s in archived if s not in named] if everything else named


def pending(services, rec: JobRecord) -> bool:
    """Ask the question first: not answered yet, and a set is named like the Disc."""
    return sets.answer(rec) is None and bool(offered(services, rec))


def page(request: Request, services, rec: JobRecord, everything: bool = False,
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
        "current": "/review", "record": rec, "tv": kind_of(rec) == SetKind.TV,
        "titles": len(ripped_titles(rec)), "sets": offer, "picked": picked,
        "part": form.get("part") or ("no" if (ans and not ans.key) or not offer else "yes"),
        "disc": form.get("disc") or (ans.number if ans and ans.key else
                                     chosen.next_number if chosen else 1),
        "errors": errors or [], "done": done_note(request),
    }
    return TEMPLATES.TemplateResponse(request, "review_set.html", ctx, status_code=status_code)


def _video_in_review(services, job_id: int) -> JobRecord | None:
    rec = services.jobs.get(job_id)
    if rec is None or rec.disc_type not in VIDEO_DISC_TYPES:
        raise HTTPException(404, "No such video Job")
    return rec if rec.status == JobStatus.REVIEW else None


@router.get("/review/{job_id}/set")
def ask(request: Request, job_id: int) -> Response:
    services = _services(request)
    rec = _video_in_review(services, job_id)
    if rec is None:
        return RedirectResponse(f"/jobs/{job_id}", status_code=303)
    return page(request, services, rec, everything=True)


@router.post("/review/{job_id}/set")
def answer(request: Request, job_id: int, part: Annotated[str, Form()] = "",
           set_: Annotated[str, Form(alias="set")] = "", disc: Annotated[str, Form()] = "") -> Response:
    services = _services(request)
    rec = _video_in_review(services, job_id)
    if rec is None:
        return RedirectResponse("/review", status_code=303)
    if part == "no":
        sets.save_answer(rec, Answer(None))
        services.sets.detach(rec.id)
        services.jobs.log(rec.id, "Review: not part of a set")
        return RedirectResponse(f"/review/{rec.id}", status_code=303)
    if part != "yes":
        raise HTTPException(400, "part is yes or no")
    key = SetKey.parse(set_)
    chosen = services.sets.find(key) if key and key.kind == kind_of(rec) else None
    number = int(disc) if disc.strip().isdigit() else 0
    errors = []
    if chosen is None:
        errors.append("Pick the set this Disc belongs to")
    elif number < 1:
        errors.append("Enter which Disc of the set this is (1 or more)")
    elif number in chosen.numbers:
        errors.append(f"Disc {number} of {chosen.name} is already archived: "
                      "check the number on the Disc")
    if errors:
        return page(request, services, rec, everything=True, errors=errors, status_code=400,
                    form={"part": part, "set": set_, "disc": disc})
    assert chosen is not None
    sets.save_answer(rec, Answer(chosen.key, number))
    services.sets.attach(rec.id, chosen.key, number)
    services.jobs.log(rec.id, f"Review: Disc {number} of the set {chosen.name}")
    if chosen.key.kind == SetKind.TV:
        return RedirectResponse(f"/review/{rec.id}", status_code=303)
    _file_as_extras_disc(services, rec, chosen)
    return after_decision(request, rec.id, f"Done: Extras Disc for {chosen.name}",
                          "Every Title on it is encoded next, then archived with the film's "
                          "Extras.")


def _file_as_extras_disc(services, rec: JobRecord, film_set: DiscSet) -> None:
    """Queue every ripped Title as an Extra of the film and hand the Disc back."""
    titles = ripped_titles(rec)
    paths = sets.extras_disc_paths(film_set, rec, titles)
    services.tv_archive.titles.enqueue(rec.id, film_set.show,
                                       [(t.number, None, paths[t.number]) for t in titles])
    if services.jobs.requeue(rec.id):
        services.jobs.log(rec.id, f"Queued {len(titles)} Title{'s' if len(titles) != 1 else ''}"
                                   f" for Encode as Extras of {film_set.name}")
        for topic in (Topic.REVIEW, Topic.RIP, Topic.ENCODE):
            services.bus.publish(topic)
