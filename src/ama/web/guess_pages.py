"""The rip card's "Change": search TMDB and pick the film a video Job is (its Best guess).

`GET /jobs/{id}/guess/search?q=` renders the results into the card (closest
runtime to the longest Title first, once the Title scan has it); `POST
/jobs/{id}/guess` stores the pick at once (film_guess.py) and goes back to `next`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from ama.events import Topic
from ama.jobs import JobRecord, JobStatus
from ama.moviereview import short_duration
from ama.tmdb import TmdbError
from ama.video_rip import VIDEO_DISC_TYPES
from ama.web import TEMPLATES

router = APIRouter()

_CHANGEABLE = (JobStatus.RIPPING, JobStatus.RIPPED)  # Review has its own film picker


def _job(request: Request, job_id: int) -> JobRecord:
    rec = request.app.state.services.jobs.get(job_id)
    if rec is None or rec.disc_type not in VIDEO_DISC_TYPES:
        raise HTTPException(404, "No such video Job")
    return rec


def _longest_s(rec: JobRecord) -> int | None:
    return max((t.duration_s for t in rec.titles), default=None)


def _back(next_: str) -> str:
    """Only back to a page of ours."""
    return next_ if next_.startswith("/") and not next_.startswith("//") else "/"


@router.get("/jobs/{job_id}/guess/search", response_class=HTMLResponse)
def search(request: Request, job_id: int, q: str = "", next: str = "/") -> Response:
    services = request.app.state.services
    rec = _job(request, job_id)
    films, error = [], None
    if not services.film_guesses.configured:
        error = "Searching needs a TMDB API key ([tmdb] api_key in Settings)."
    elif q.strip():
        try:
            films = services.film_guesses.search(q.strip(), _longest_s(rec))
        except TmdbError as e:
            error = str(e)
    rows = [(f, " · ".join([*([f.director] if f.director else []),
                             *([short_duration(f.runtime_min * 60)] if f.runtime_min else [])]))
            for f in films]
    return TEMPLATES.TemplateResponse(request, "partials/guess_results.html", {
        "job": rec, "q": q.strip(), "films": rows, "error": error, "next": _back(next),
        "changeable": rec.status in _CHANGEABLE})


@router.post("/jobs/{job_id}/guess")
def pick(request: Request, job_id: int, film: Annotated[int, Form()],
         next: Annotated[str, Form()] = "/") -> Response:
    services = request.app.state.services
    rec = _job(request, job_id)
    if rec.status not in _CHANGEABLE:
        raise HTTPException(409, "This Job's film is chosen in Review now")
    try:
        guess = services.film_guesses.pick(job_id, film)
    except TmdbError as e:
        raise HTTPException(502, str(e)) from None
    services.jobs.log(job_id, f"You picked {guess.name} (TMDB {guess.film.id}) as the film")
    services.bus.publish(Topic.RIP)
    services.bus.publish(Topic.DRIVE)
    return RedirectResponse(_back(next), status_code=303)
