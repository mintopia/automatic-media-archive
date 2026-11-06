"""TV Review: pick the series on TMDB, then each Title's Episode (or Extra/Discard).

`GET /review/{id}` for a TV Disc renders `page()` (dispatched from review_pages).
The series is the one picked or guessed while it ripped (series_guess.py), else the
first TMDB match for the Disc's names, unless `?series=` picks one; `?q=` (or `?change`) shows a series search instead; `?season=` picks the
season whose Episodes are offered (specials are always offered as well). Each
Title shows the Thumbnailer's stills. `POST /review/{id}/episodes` queues the
kept Titles for Encode (`TvTitles.enqueue`) and hands the Disc back to the
pipeline; `POST /review/{id}/kind` marks a Disc TV or a film.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from ama import naming, sets, tvreview
from ama.config import LibraryKind, library_for
from ama.jobs import JobRecord, JobStatus
from ama.moviereview import ripped_titles
from ama.sets import SetKind, SetKey
from ama.tmdb import Episode, Series, TmdbError, load_hints
from ama.tv import play_alls, season_path, series_terms
from ama.tvarchive import planned
from ama.video_rip import VIDEO_DISC_TYPES
from ama.web import TEMPLATES, view_context
from ama.web.movie_review_pages import TitleChoice, _title_choice
from ama.web.review_items import after_decision, done_note, plural
from ama.events import Topic

router = APIRouter()


@dataclass(frozen=True)
class TvTitle:
    choice: TitleChoice  # the Title, its note and stills
    play_all: bool
    picked: str          # its option value: "S01E04", "extra", "discard"


def _services(request: Request):
    return request.app.state.services


def _video_in_review(services, job_id: int) -> JobRecord | None:
    rec = services.jobs.get(job_id)
    if rec is None or rec.disc_type not in VIDEO_DISC_TYPES:
        raise HTTPException(404, "No such video Job")
    return rec if rec.status == JobStatus.REVIEW else None


def _int(value: str | None) -> int | None:
    return int(value) if value and value.strip().isdigit() else None


def _default_season(series: Series) -> int:
    return min((s for s in series.seasons if s > 0), default=0 if series.seasons else 1)


def _after_earlier_discs(services, rec: JobRecord, series: Series | None, season: int | None,
                         episodes: list[Episode]) -> list[Episode]:
    """The season's Episodes after the last one other Discs of the series took: a
    later Disc of a set carries on. Attached as Disc N, only Discs numbered below N count."""
    if series is None or season is None:
        return episodes
    earlier: set[int] | None = None
    ans = sets.answer(rec)
    if ans and ans.key == SetKey(SetKind.TV, series.id, season):
        filed = services.sets.find(ans.key)
        earlier = {d for d, n in filed.members if n < ans.number} if filed else set()
    taken = [t.episode.number for t in services.tv_archive.titles.in_season(series.id, season)
             if t.episode and t.job_id != rec.id and (earlier is None or t.job_id in earlier)]
    last = max(taken, default=0)
    return [e for e in episodes if e.number > last]


def tv_pattern(services, rec: JobRecord) -> str:
    """The Naming Pattern of the TV Library `rec` would file to now."""
    library = (services.job_settings.files_to(rec, LibraryKind.TV) if services.job_settings
               else library_for(services.archive.libraries, LibraryKind.TV))
    return naming.pattern_of(library)


def page(request: Request, services, rec: JobRecord, errors: list[str] | None = None,
         status_code: int = 200, series_id: int | None = None, season: int | None = None,
         chosen: dict[int, str] | None = None) -> Response:
    params = request.query_params
    tmdb = services.tmdb
    terms = series_terms(load_hints(rec.scratch_dir, rec.label))
    searching = "q" in params or "change" in params
    q = (params.get("q") or "").strip() if "q" in params else (terms or [""])[0]
    series_id = series_id or _int(params.get("series"))
    season = season if season is not None else _int(params.get("season"))
    attached = sets.answer(rec)
    if (attached and attached.key and attached.key.kind == SetKind.TV and not searching
            and series_id is None):
        series_id, season = attached.key.tmdb_id, attached.key.season
    if series_id is None and not searching and (guess := services.series_guesses.get(rec.id)):
        series_id = guess.series.id
    results: list[Series] = []
    series: Series | None = None
    episodes: list[Episode] = []
    specials: list[Episode] = []
    tmdb_error = None
    try:
        if searching:
            results = tmdb.search_tv(q) if q else []
        else:
            if series_id is None:
                for term in terms:
                    if results := tmdb.search_tv(term):
                        series_id = results[0].id
                        break
            if series_id:
                series = tmdb.series(series_id)
                if season is None or (series.seasons and season not in series.seasons):
                    season = _default_season(series)
                episodes = tmdb.season(series.id, season)
                if season != 0 and 0 in series.seasons:
                    specials = tmdb.season(series.id, 0)
    except TmdbError as e:
        tmdb_error = str(e)
    titles = ripped_titles(rec)
    joined = play_alls(titles)
    picks = chosen or tvreview.suggest(
        titles, _after_earlier_discs(services, rec, series, season, episodes))
    ctx = view_context(services) | {
        "current": "/review", "record": rec, "q": q, "searching": searching or series is None,
        "results": results, "series": series, "season": season or 0,
        "seasons": series.seasons if series and series.seasons else ([season] if series else []),
        "episodes": episodes, "specials": specials, "tmdb_error": tmdb_error,
        "folder": season_path(series, season or 0, tv_pattern(services, rec)).as_posix()
        if series else "",
        "titles": [TvTitle(_title_choice(services, rec, t, None), t.number in joined,
                           picks.get(t.number, tvreview.EXTRA)) for t in titles],
        "errors": errors or [], "done": done_note(request),
        "extra": tvreview.EXTRA, "discard": tvreview.DISCARD,
    }
    return TEMPLATES.TemplateResponse(request, "review_tv.html", ctx, status_code=status_code)


@router.post("/review/{job_id}/kind")
def kind(request: Request, job_id: int, kind: Annotated[str, Form()] = "") -> Response:
    """Mark a Disc in Review as TV (`kind=tv`) or a film (`kind=film`)."""
    services = _services(request)
    rec = _video_in_review(services, job_id)
    if rec is None:
        return RedirectResponse("/review", status_code=303)
    if kind not in ("tv", "film"):
        raise HTTPException(400, "kind is tv or film")
    tvreview.mark(rec, kind == "tv")
    services.jobs.log(rec.id, f"Review: marked as {'TV' if kind == 'tv' else 'a film'}")
    return RedirectResponse(f"/review/{rec.id}", status_code=303)


@router.post("/review/{job_id}/episodes")
async def episodes(request: Request, job_id: int) -> Response:
    services = _services(request)
    rec = _video_in_review(services, job_id)
    if rec is None:
        return RedirectResponse("/review", status_code=303)
    form = await request.form()
    series_id, season = _int(str(form.get("series", ""))), _int(str(form.get("season", "")))
    if not series_id:
        raise HTTPException(400, "Pick a series")
    titles = ripped_titles(rec)
    choices = {t.number: str(form.get(f"t{t.number}", "")) for t in titles}
    seasons = {s for c in choices.values() if (s := tvreview.season_of(c)) is not None}
    try:
        series = services.tmdb.series(series_id)
        known = {e.code: e for s in sorted(seasons) for e in services.tmdb.season(series_id, s)}
    except TmdbError as e:
        return page(request, services, rec, [f"Couldn't look the series up: {e}. Try again."],
                    503, series_id, season, choices)
    kept, errors = tvreview.decide(titles, choices, known)
    if errors:
        return page(request, services, rec, errors, 400, series_id, season, choices)
    paths = planned(series, rec, kept, tv_pattern(services, rec))
    services.tv_archive.titles.enqueue(rec.id, series, paths)
    n = sum(1 for k in kept if k.episode)
    if services.jobs.requeue(rec.id):
        services.jobs.log(rec.id, f"Review: {series.title} (TMDB {series.id}); "
                                   + "; ".join(f"Title {k.title.number} = "
                                               f"{k.episode.code if k.episode else 'Extra'}"
                                               for k in kept)
                                   + f"; {len(titles) - len(kept)} discarded")
        services.jobs.log(rec.id, f"Queued {n} Episode{'s' if n != 1 else ''} for Encode")
        for topic in (Topic.REVIEW, Topic.RIP, Topic.ENCODE):
            services.bus.publish(topic)
    return after_decision(request, rec.id, f"Done: {series.title} · {plural(n, 'Episode')}",
                          "They're encoded next, then filed to TV. Follow them under Encoding "
                          "on Now.")
