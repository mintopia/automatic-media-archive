"""Movie Review: pick the film on TMDB and the Title that is the Main Feature.

`GET /review/{id}` for a video Disc renders `page()` (dispatched from
review_pages). The films offered are the ones Identification's search found (`tmdb.json`);
`?q=` searches TMDB again. Each ripped Title shows stills at 10/50/90% that the
Thumbnailer takes in the background; until they exist the frames poll
`/review/{id}/titles/{n}/frames`. Confirming queues the Encode
(`Movies.enqueue`) and hands the Disc back to the Encode pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response

from ama import decoys, moviereview, naming
from ama.config import LibraryKind, library_for
from ama.jobs import JobRecord, JobStatus, ReviewReason, TitleRecord
from ama.extras import extra_titles
from ama.moviearchive import main_feature
from ama.moviereview import POSITIONS, fits, ripped_titles, runtime_note, short_duration, \
    thumb_path
from ama.tmdb import Candidate, TmdbError, movie_folder, search_terms, load_hints
from ama.video_rip import VIDEO_DISC_TYPES
from ama.web import TEMPLATES, view_context
from ama.web.review_items import FILM_UNSURE, after_decision, done_note, plural
from ama.events import Topic

router = APIRouter()


@dataclass(frozen=True)
class FilmChoice:
    film: Candidate
    note: str   # "Michael Mann · 2 h 50 m · matches the Disc"
    fits: bool
    best: bool = False  # the Job's Best guess (film_guess.py)


@dataclass(frozen=True)
class Frame:
    pct: int
    src: str | None  # None: not taken (yet)


@dataclass(frozen=True)
class TitleChoice:
    title: TitleRecord
    label: str         # "Title 6", or "Title 6 · 00805.mpls" for a decoy version
    note: str          # "2 h 50 m 14 s · likely the film"
    frames: tuple[Frame, ...]
    pending: bool      # some stills are still being taken


def _services(request: Request):
    return request.app.state.services


def _video_in_review(services, job_id: int) -> JobRecord | None:
    rec = services.jobs.get(job_id)
    if rec is None or rec.disc_type not in VIDEO_DISC_TYPES:
        raise HTTPException(404, "No such video Job")
    return rec if rec.status == JobStatus.REVIEW else None


def _title_choice(services, rec: JobRecord, t: TitleRecord, main: TitleRecord | None,
                  found: decoys.Decoys | None = None) -> TitleChoice:
    frames = []
    for pct in POSITIONS:
        ready = thumb_path(rec.scratch_dir, t.number, pct).exists()
        frames.append(Frame(pct, f"/review/{rec.id}/titles/{t.number}/frames/{pct}.jpg"
                            if ready else None))
    pending = any(f.src is None and (rec.id, t.number, f.pct) not in services.thumbnails.failed
                  for f in frames)
    note, label = short_duration(t.duration_s, with_seconds=True), f"Title {t.number}"
    if found is not None and t in found.versions:
        label += f" · {t.source}" if t.source else ""
        if found.confident:
            note += " · likely the film" if t == found.likely else " · scenes out of order"
    elif found is None and main is not None and t.number == main.number:
        note += " · the longest, likely the film"
    return TitleChoice(t, label, note, tuple(frames), pending)


def _ordered(titles: list[TitleRecord], main: TitleRecord | None,
             found: decoys.Decoys | None) -> list[TitleRecord]:
    """The picked Title first; with decoys, the other versions next; then longest first."""
    def key(t: TitleRecord):
        version = found is not None and t in found.versions
        return (main is None or t.number != main.number, not version,
                0 if version else -t.duration_s, t.number)
    return sorted(titles, key=key)


def _more_label(hidden: list[TitleRecord], found: decoys.Decoys | None) -> str:
    """"Show 11 more versions and 2 other Titles" for the collapsed rows."""
    versions = sum(found is not None and t in found.versions for t in hidden)
    others = len(hidden) - versions
    parts = [plural(versions, "more version")] if versions else []
    if others:
        parts.append(plural(others, "other Title" if versions else "more Title"))
    return "Show " + " and ".join(parts)


def _film_choice(film: Candidate, duration_s: int, best: bool = False) -> FilmChoice:
    parts = [film.director] if film.director else []
    if film.runtime_min:
        parts.append(short_duration(film.runtime_min * 60))
    parts.append(runtime_note(film, duration_s))
    return FilmChoice(film, " · ".join(parts), fits(film, duration_s), best)


def _find_film(services, rec: JobRecord, film_id: int) -> Candidate:
    """The chosen film: from the saved search if it's there, else asked of TMDB."""
    saved = next((c for c in moviereview.saved_search(rec.scratch_dir).candidates
                  if c.id == film_id), None)
    return saved or services.tmdb.movie(film_id)


def page(request: Request, services, rec: JobRecord, errors: list[str] | None = None,
         status_code: int = 200) -> Response:
    titles = ripped_titles(rec)
    found = decoys.detect(titles)
    main = found.likely if found else main_feature(rec.titles)
    main_s = main.duration_s if main else 0
    saved = moviereview.saved_search(rec.scratch_dir)
    guess = services.film_guesses.get(rec.id)
    best = guess.film if guess else None
    q = request.query_params.get("q")
    search_error = None
    if q is not None and q.strip():
        try:
            films = services.tmdb.search(q.strip())
        except TmdbError as e:
            films, search_error = [], str(e)
    else:
        q = (saved.terms or search_terms(load_hints(rec.scratch_dir, rec.label)) or [""])[0]
        films = sorted(saved.candidates, key=lambda c: not fits(c, main_s))
        if best is not None:  # Review starts from the Best guess
            films = [best, *(f for f in films if f.id != best.id)]
    choices = [_film_choice(f, main_s, best is not None and f.id == best.id) for f in films]
    picked_film = _preselect(rec, guess, choices)
    ordered = _ordered(titles, main, found)
    shown = 3 if found else 4
    ctx = view_context(services) | {
        "current": "/review", "record": rec, "q": q, "searched": "q" in request.query_params,
        "search_error": search_error, "films": choices, "picked_film": picked_film,
        "titles": [_title_choice(services, rec, t, main, found) for t in ordered],
        "shown": shown, "more_label": _more_label(ordered[shown:], found), "decoys": found,
        "picked_title": main, "main_length": short_duration(main_s),
        "errors": errors or [], "done": done_note(request),
        "summary": _summary(services, picked_film, main, rec),
        "notice": _notice(rec, guess.film if guess and guess.picked else None,
                          short_duration(main_s)),
    }
    return TEMPLATES.TemplateResponse(request, "review_movie.html", ctx, status_code=status_code)


def _preselect(rec: JobRecord, guess, choices: list[FilmChoice]) -> Candidate | None:
    """The film ticked when the page opens. When AMA is unsure which film it is, only the
    person's own pick from while it ripped is ticked: they choose, AMA doesn't."""
    if guess is not None and guess.picked:
        return guess.film
    if rec.review_reason in FILM_UNSURE:
        return None
    best = next((c.film for c in choices if c.best), None)
    return best or next((c.film for c in choices if c.fits), choices[0].film if choices else None)


@dataclass(frozen=True)
class Notice:
    head: str
    body: str


_WHY: dict[ReviewReason, Notice] = {
    ReviewReason.NO_MATCH: Notice(
        "We couldn't find this film",
        "The Disc's label doesn't match a film in the film database (TMDB). Search for the "
        "film's title, then pick it."),
    ReviewReason.RUNTIME_MISMATCH: Notice(
        "No film here runs as long as the Disc",
        "These films have the right name, but none runs close to the main Title ({main}). "
        "Check the pictures, then pick the film or search for another."),
    ReviewReason.MULTIPLE_MATCHES: Notice(
        "Several films fit this Disc",
        "They have a similar name and running time, so we can't tell which it is. Check the "
        "pictures, then pick the film on the Disc."),
}


def _notice(rec: JobRecord, pick: Candidate | None, main: str) -> Notice | None:
    """Why the Disc is in Review, when the reason is which film it is."""
    if rec.review_reason == ReviewReason.PICK_RUNTIME_MISMATCH and pick is not None:
        runs = (f"runs {short_duration(pick.runtime_min * 60)}" if pick.runtime_min
                else "has no running time in the film database (TMDB)")
        return Notice("Your pick doesn't match the Disc's length",
                      f"The film you picked {runs}; the main Title runs {main}. "
                      "Check it's the right film, or pick another.")
    why = _WHY.get(rec.review_reason)
    return Notice(why.head, why.body.format(main=main)) if why else None


def _summary(services, film: Candidate | None, title: TitleRecord | None,
             rec: JobRecord) -> dict:
    n = len(extra_titles(rec.titles, title.number)) if title else 0
    return {"film": film.name if film else "",
            "title": f"Title {title.number} · {short_duration(title.duration_s)}" if title else "",
            "extras": f"{n} Extra{'s' if n != 1 else ''}, archived under Other" if n else "",
            "folder": movie_folder(film, film_pattern(services, rec)).as_posix() if film else ""}


def film_pattern(services, rec: JobRecord) -> naming.Pattern:
    """The Naming Pattern of the Films Library `rec` would archive to now."""
    library = (services.job_settings.files_to(rec, LibraryKind.FILMS) if services.job_settings
               else library_for(services.archive.libraries, LibraryKind.FILMS))
    return naming.pattern_of(library)


@router.get("/review/{job_id}/titles/{number}/frames", response_class=HTMLResponse)
def frames(request: Request, job_id: int, number: int) -> Response:
    services = _services(request)
    rec = services.jobs.get(job_id)
    if rec is None or rec.disc_type not in VIDEO_DISC_TYPES:
        raise HTTPException(404, "No such video Job")
    t = next((t for t in ripped_titles(rec) if t.number == number), None)
    if t is None:
        raise HTTPException(404, "No such Title")
    choice = _title_choice(services, rec, t, None, decoys.detect(ripped_titles(rec)))
    return TEMPLATES.TemplateResponse(request, "partials/title_frames.html",
                                      {"record": rec, "t": choice})


@router.get("/review/{job_id}/titles/{number}/frames/{pct}.jpg")
def frame(request: Request, job_id: int, number: int, pct: int) -> Response:
    rec = _services(request).jobs.get(job_id)
    if rec is None or pct not in POSITIONS:
        raise HTTPException(404, "No such picture")
    path = thumb_path(rec.scratch_dir, number, pct)
    if not path.is_file():
        raise HTTPException(404, "No such picture")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "no-cache"})


@router.get("/review/{job_id}/decision", response_class=HTMLResponse)
def decision(request: Request, job_id: int, film: int = 0, title: int = 0) -> Response:
    """The "When you confirm" facts for the film and Title currently picked."""
    services = _services(request)
    rec = _video_in_review(services, job_id)
    if rec is None:
        return HTMLResponse("")
    t = next((t for t in ripped_titles(rec) if t.number == title), None)
    try:
        candidate = _find_film(services, rec, film) if film else None
    except TmdbError:
        candidate = None
    return TEMPLATES.TemplateResponse(request, "partials/movie_decision.html",
                                      {"summary": _summary(services, candidate, t, rec)})


@router.post("/review/{job_id}/film", response_class=HTMLResponse)
def confirm(request: Request, job_id: int, film: Annotated[int, Form()] = 0,
            title: Annotated[int, Form()] = 0) -> Response:
    services = _services(request)
    rec = _video_in_review(services, job_id)
    if rec is None:
        return RedirectResponse("/review", status_code=303)
    t = next((t for t in ripped_titles(rec) if t.number == title), None)
    if t is None:
        raise HTTPException(400, "That Title isn't one of this Job's ripped Titles")
    if not film:
        raise HTTPException(400, "Pick a film")
    try:
        candidate = _find_film(services, rec, film)
    except TmdbError as e:
        return page(request, services, rec, [f"Couldn't look the film up: {e}. Try again."],
                    status_code=503)
    services.movie_archive.movies.enqueue(rec.id, candidate, t.number)
    if services.jobs.requeue(rec.id):
        services.jobs.log(rec.id, f"Review: identified as {candidate.name} (TMDB "
                                   f"{candidate.id}); Main Feature is Title {t.number} "
                                   f"({t.duration})")
        services.jobs.log(rec.id, "Queued for Encode")
        for topic in (Topic.REVIEW, Topic.RIP, Topic.ENCODE):
            services.bus.publish(topic)
    return after_decision(request, rec.id, f"Done: {candidate.name}",
                          "It's encoded next, then archived to Movies. Follow it under Encoding "
                          "on Now.")
