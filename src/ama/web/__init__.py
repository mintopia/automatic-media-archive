"""Server-rendered UI: Jinja templates, htmx, live fragments over SSE.

A *fragment* is a partial template bound to a bus topic. The page includes it
inside `<div sse-swap="TOPIC">`; when TOPIC is published, every open
`/events` stream re-renders the partial and the browser swaps it in.
To make something live: add a partial, register it in FRAGMENTS, and have its
owner `bus.publish(topic)` when the state behind it changes.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape

from ama.cdrip import CdJob
from ama.jobs import JobStatus
from ama.extras import ExtraStatus
from ama.media import Album
from ama.moviearchive import FiledMovie
from ama.phase import phase_of
from ama.tvarchive import FiledTv
from ama.web import auth
from ama.web.current_rip import current_rip
from ama.web.now_output import step_output
from ama.web.review_items import review_items
from ama.web.scratch_items import scratch_context
from ama.video_rip import VIDEO_DISC_TYPES
from ama.tools import NEEDED_FOR, ToolDownloading, ToolFailed, ToolNotFound, makemkv_headline

if TYPE_CHECKING:
    from ama.app import Services

HERE = Path(__file__).parent
STATIC_DIR = HERE / "static"
TEMPLATES = Jinja2Templates(directory=HERE / "templates")
# `{% if state | kind == "DiscPresent" %}`: branch on which variant a state union holds.
TEMPLATES.env.filters["kind"] = lambda value: type(value).__name__
TEMPLATES.env.filters["makemkv_headline"] = makemkv_headline
# `{% set p = job.status | phase %}<span class="stk {{ p.css }}">{{ p }}</span>`: status as a Phase.
TEMPLATES.env.filters["phase"] = phase_of


def breakable_path(path: object) -> Markup:
    """A path that wraps after its separators on narrow screens, not mid-name."""
    return Markup(str(escape(str(path))).replace("\\", "\\<wbr>").replace("/", "/<wbr>"))


TEMPLATES.env.filters["path"] = breakable_path

# Top-bar navigation, in order. Add a page here when its ticket ships.
NAV: list[tuple[str, str]] = [("Now", "/"), ("Review", "/review"), ("History", "/history")]
# Top-bar menu links (label, href, icons.svg id), shown between Theme and Log out.
# Settings and Logs live here, not in NAV; a page is current on its href and below it.
MENU: list[tuple[str, str, str]] = [("Settings", "/settings", "settings"), ("Logs", "/logs", "log")]

FRAGMENTS: dict[str, str] = {
    "drive": "partials/drive.html",
    "nas": "partials/nas.html",
    "tools": "partials/tools.html",
    "rip": "partials/rip.html",
    "ripping": "partials/ripping_bin.html",
    "rip-failed": "partials/rip_failed.html",
    "cd-rip": "partials/cd_rip_live.html",
    "filed": "partials/filed_bin.html",
    "encode": "partials/encoding_bin.html",
    "review": "partials/review_bin.html",
    "review-count": "partials/review_count.html",
    "drive-status": "partials/drive_status.html",
    "problems": "partials/problems.html",  # app-wide banners (problems.py)
    # Nothing to show: run pages fetch their live output on its SSE event (`sse:logs`).
    "logs": "partials/logs_tick.html",
    # The scratch page body: one partial, live on each topic that changes what it shows.
    "scratch": "partials/scratch.html",
    "scratch-rip": "partials/scratch.html",
    "scratch-encode": "partials/scratch.html",
    "pause": "partials/paused_mark.html",
    "pause-menu": "partials/pause_menu.html",
    "pause-settings": "partials/settings_pause_now.html",
}
# A fragment re-renders when the bus topic of the same name is published, or the
# topic named here (several fragments can follow one topic).
FRAGMENT_TOPICS: dict[str, str] = {"ripping": "rip", "cd-rip": "rip", "rip-failed": "rip",
                                   "scratch-rip": "rip", "scratch-encode": "encode",
                                   "review-count": "review", "drive-status": "drive",
                                   "pause-menu": "pause", "pause-settings": "pause"}


def fragments_for(topic: str) -> list[str]:
    return [name for name in FRAGMENTS if FRAGMENT_TOPICS.get(name, name) == topic]


def _minutes(seconds: float) -> str:
    m = round(seconds / 60)
    return f"{m // 60} h {m % 60} m" if m >= 60 else f"{max(m, 1)} min"


def _mmss(seconds: float) -> str:
    s = round(seconds)
    return f"{s // 60}:{s % 60:02d}"


def _left(seconds: int) -> str:
    return "under a minute left" if seconds < 60 else f"{_minutes(seconds)} left"


TEMPLATES.env.filters.update(minutes=_minutes, mmss=_mmss, left=_left)


def view_context(services: Services) -> dict[str, Any]:
    """Everything templates (pages and fragments) may read. Keep it plain data."""
    scratch = services.scratch.usage()
    cd = services.cd
    return {
        "nav": NAV,
        "menu": MENU,
        "can_log_out": auth.auth_required(services),
        "paused": services.pause.paused,  # new Discs ignored (GLOSSARY.md Paused)
        "review": review_items(services),
        # The Rip under way, any Disc Type: the drive card and Ripping bin both read this.
        "current_rip": current_rip(services),
        # (Job id, Step key) -> the running Step's newest lines for Now's "Show output", or None
        "output_of": lambda job_id, key: step_output(services, job_id, key),
        "cd": cd.current,
        "cd_reading": cd.reading_toc,
        "cd_last_id": cd.last_job_id,
        "ripped": cd.jobs(JobStatus.RIPPED),
        "failed": cd.jobs(JobStatus.FAILED),
        # video Jobs ripped and not yet identified (still in the Ripping Phase)
        "ripped_video": [d for d in services.jobs.list(JobStatus.RIPPED, types=VIDEO_DISC_TYPES)
                         if services.movie_archive.movies.get(d.id) is None
                         and not services.tv_archive.titles.has(d.id)],
        "waiting_for": services.problems.why,  # Job id -> Waiting (why it can't move on) | None
        "problems": services.problems.banners(),
        "filed": [d for d in filed_jobs(services)
                  if d.record.filed_at and d.record.filed_at.date() == date.today()],
        "media_of": services.media.get,  # what a filed Disc is (cover, poster), media.py
        "contents_of": lambda d: contents_of(services, d),
        **services.movie_archive.queue_view(),
        **services.tv_archive.queue_view(),  # TV Episodes not yet filed
        "drive": services.drive.state,
        "repeat": services.repeat.pending,  # an archived Disc waiting for the user
        "nas": services.nas.status,
        "encoder_problem": services.encoders.problem(),  # the configured encoder failed its test
        "nas_retry_seconds": services.config.nas.retry_seconds,
        "scratch": scratch,
        "scratch_refused": services.scratch.refused,
        "scratch_view": lambda: scratch_context(services),  # walks scratch: call only if shown
        # Video Rip: the Disc being ripped (else the last one), and its live progress.
        "rip_job": services.video_rip.job,
        "rip_progress": services.video_rip.progress,
        "jobset_of": lambda job: _jobset_view(services, job),  # per-Job settings panel (#30)
        "guess_of": services.film_guesses.get,  # Job id -> its Best guess (film_guess.py)
        "guessing": services.video_rip.guessing,  # TMDB is still being asked for it
        "guess_search": services.film_guesses.configured,  # a TMDB key: the guess can change
        "rip_failure": next(iter(services.jobs.list(JobStatus.FAILED, types=VIDEO_DISC_TYPES)),
                            None),
        **_tools_context(services),
    }


def _jobset_view(services: Services, job: Any) -> Any:
    from ama.web.job_settings_pages import jobset_view  # it imports this module
    return jobset_view(services, job)


def filed_jobs(services: Services, limit: int = 100) -> list:
    """Filed Discs, newest first, as CdJobs, FiledMovies and FiledTv (History)."""
    return sorted([*services.cd.jobs(JobStatus.FILED, limit=limit),
                   *services.movie_archive.filed(limit), *services.tv_archive.filed(limit)],
                  key=lambda d: (d.record.filed_at or d.record.started_at, d.record.id),
                  reverse=True)[:limit]


def contents_of(services: Services, d: Any) -> list[str]:
    """What a filed Disc holds, by name, for its History row: tracks, Episodes or Extras."""
    if isinstance(d, CdJob):
        album = services.media.get(d.record.id)
        return [f"{t.number}. {album.track_title(t.number) or f'Track {t.number}'}"
                for t in d.tracks if t.number] if isinstance(album, Album) else []
    if isinstance(d, FiledMovie):
        return [e.name for e in services.movie_archive.extras.of(d.record.id)
                if e.status == ExtraStatus.FILED]
    if isinstance(d, FiledTv):
        return [f"{t.episode.code} · {t.episode.name}" if t.episode else f"Extra · {t.path.stem}"
                for t in d.episodes]
    return []


def _tools_context(services: Services) -> dict[str, Any]:
    tools = services.tools
    managed = []
    for pin in tools.pins:
        for m in pin.members:
            st = tools.status(m.name)
            entry = {"status": st, "needed_for": NEEDED_FOR[m.name]}
            # One notice per download (its members share it); one per missing override.
            if isinstance(st, ToolDownloading | ToolFailed | ToolNotFound) and entry not in managed:
                managed.append(entry)
    return {"tools": managed, "makemkv": tools.status("makemkvcon"),
            "retry_seconds": tools.retry_seconds}


# Fragments that are only a signal (their event triggers a fetch): rendered with no state.
BARE_FRAGMENTS = {"logs"}


def render_fragment(topic: str, services: Services) -> str:
    if topic in BARE_FRAGMENTS:  # skip building the whole view context, many times a second
        return TEMPLATES.get_template(FRAGMENTS[topic]).render()
    return TEMPLATES.get_template(FRAGMENTS[topic]).render(view_context(services))
