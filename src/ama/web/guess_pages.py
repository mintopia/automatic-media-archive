"""The rip card's "Change": search TMDB and pick the film a video Job is (its Best guess).

`GET /jobs/{id}/guess/search?q=` renders the results into the card (closest
runtime to the longest Title first, once the Title scan has it); `POST
/jobs/{id}/guess` stores the pick at once (film_guess.py) and goes back to `next`.
`POST /jobs/{id}/kind` marks the Disc as TV (or a film after all) before Identification:
TV then goes to TV Review, to match its Titles to Episodes (tvreview.py). Marked TV, the
series is guessed (series_guess.py); `GET /jobs/{id}/series/search?q=` and `POST
/jobs/{id}/series` change it the way the film's are.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from ama import tvreview
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


@router.post("/jobs/{job_id}/kind")
def kind(request: Request, job_id: int, kind: Annotated[str, Form()], tasks: BackgroundTasks,
         next: Annotated[str, Form()] = "/") -> Response:
    """Mark a video Job as TV (`kind=tv`) or a film (`kind=film`) while it rips."""
    services = request.app.state.services
    rec = _job(request, job_id)
    if kind not in ("tv", "film"):
        raise HTTPException(400, "kind is tv or film")
    if rec.status not in _CHANGEABLE:
        raise HTTPException(409, "This Job is marked as TV or a film in Review now")
    tvreview.mark(rec, kind == "tv")
    services.jobs.log(job_id, "You marked the Disc as TV: its Titles are matched to Episodes "
                              "in Review" if kind == "tv" else "You marked the Disc as a film")
    if kind == "tv":
        tasks.add_task(_guess_series, services, rec)
    services.bus.publish(Topic.RIP)
    services.bus.publish(Topic.DRIVE)
    return RedirectResponse(_back(next), status_code=303)


def _guess_series(services, rec: JobRecord) -> None:
    services.series_guesses.guess(rec)
    services.bus.publish(Topic.RIP)
    services.bus.publish(Topic.DRIVE)


@router.get("/jobs/{job_id}/series/search", response_class=HTMLResponse)
def search_series(request: Request, job_id: int, q: str = "", next: str = "/") -> Response:
    services = request.app.state.services
    rec = _job(request, job_id)
    shows, error = [], None
    if not services.film_guesses.configured:
        error = "Searching needs a TMDB API key ([tmdb] api_key in Settings)."
    elif q.strip():
        try:
            shows = services.series_guesses.search(q.strip())
        except TmdbError as e:
            error = str(e)
    return TEMPLATES.TemplateResponse(request, "partials/series_results.html", {
        "job": rec, "q": q.strip(), "shows": shows, "error": error, "next": _back(next),
        "changeable": rec.status in _CHANGEABLE})


@router.post("/jobs/{job_id}/series")
def pick_series(request: Request, job_id: int, series: Annotated[int, Form()],
                next: Annotated[str, Form()] = "/") -> Response:
    services = request.app.state.services
    rec = _job(request, job_id)
    if rec.status not in _CHANGEABLE:
        raise HTTPException(409, "This Job's series is chosen in Review now")
    try:
        guess = services.series_guesses.pick(job_id, series)
    except TmdbError as e:
        raise HTTPException(502, str(e)) from None
    services.jobs.log(job_id, f"You picked {guess.name} (TMDB {guess.series.id}) as the series")
    services.bus.publish(Topic.RIP)
    services.bus.publish(Topic.DRIVE)
    return RedirectResponse(_back(next), status_code=303)
