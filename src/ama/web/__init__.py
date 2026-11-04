"""Server-rendered UI: Jinja templates, htmx, live fragments over SSE.

A *fragment* is a partial template bound to a bus topic. The page includes it
inside `<div sse-swap="TOPIC">`; when TOPIC is published, every open
`/events` stream re-renders the partial and the browser swaps it in.
To make something live: add a partial, register it in FRAGMENTS, and have its
owner `bus.publish(topic)` when the state behind it changes.
"""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi.templating import Jinja2Templates

from ama.discs import DiscStatus
from ama.video_rip import VIDEO_DISC_TYPES

if TYPE_CHECKING:
    from ama.app import Services

HERE = Path(__file__).parent
STATIC_DIR = HERE / "static"
TEMPLATES = Jinja2Templates(directory=HERE / "templates")
# `{% if state | kind == "DiscPresent" %}`: branch on which variant a state union holds.
TEMPLATES.env.filters["kind"] = lambda value: type(value).__name__

# Top-bar navigation, in order. Add a page here when its ticket ships.
NAV: list[tuple[str, str]] = [("Now", "/")]

FRAGMENTS: dict[str, str] = {
    "drive": "partials/drive.html",
    "nas": "partials/nas.html",
    "rip": "partials/rip.html",
    "ripping": "partials/ripping_bin.html",
    "rip-failed": "partials/rip_failed.html",
    "cd-rip": "partials/cd_rip_live.html",
    "filed": "partials/filed_bin.html",
}
# A fragment re-renders when the bus topic of the same name is published, or the
# topic named here (several fragments can follow one topic).
FRAGMENT_TOPICS: dict[str, str] = {"ripping": "rip", "cd-rip": "rip", "rip-failed": "rip"}


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

GB = 1000**3


def view_context(services: Services) -> dict[str, Any]:
    """Everything templates (pages and fragments) may read. Keep it plain data."""
    try:
        du = shutil.disk_usage(services.config.paths.scratch)
        scratch = {"used_gb": round(du.used / GB), "total_gb": round(du.total / GB),
                   "pct": round(100 * du.used / du.total, 1) if du.total else 0}
    except OSError:
        scratch = None
    cd = services.cd
    return {
        "nav": NAV,
        "cd": cd.current,
        "cd_reading": cd.reading_toc,
        "cd_last_id": cd.last_disc_id,
        "ripped": cd.discs(DiscStatus.RIPPED),
        "failed": cd.discs(DiscStatus.FAILED),
        "filed": [d for d in cd.discs(DiscStatus.FILED, limit=100)
                  if d.record.filed_at and d.record.filed_at.date() == date.today()],
        "drive": services.drive.state,
        "nas": services.nas.status,
        "nas_retry_seconds": services.config.nas.retry_seconds,
        "scratch": scratch,
        # Video Rip: the Disc being ripped (else the last one), and its live progress.
        "rip_disc": services.video_rip.disc,
        "rip_progress": services.video_rip.progress,
        "rip_failure": next(iter(services.discs.list(DiscStatus.FAILED, types=VIDEO_DISC_TYPES)),
                            None),
    }


def render_fragment(topic: str, services: Services) -> str:
    return TEMPLATES.get_template(FRAGMENTS[topic]).render(view_context(services))
