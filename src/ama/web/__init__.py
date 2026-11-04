"""Server-rendered UI: Jinja templates, htmx, live fragments over SSE.

A *fragment* is a partial template bound to a bus topic. The page includes it
inside `<div sse-swap="TOPIC">`; when TOPIC is published, every open
`/events` stream re-renders the partial and the browser swaps it in.
To make something live: add a partial, register it in FRAGMENTS, and have its
owner `bus.publish(topic)` when the state behind it changes.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi.templating import Jinja2Templates

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
}

GB = 1000**3


def view_context(services: Services) -> dict[str, Any]:
    """Everything templates (pages and fragments) may read. Keep it plain data."""
    try:
        du = shutil.disk_usage(services.config.paths.scratch)
        scratch = {"used_gb": round(du.used / GB), "total_gb": round(du.total / GB),
                   "pct": round(100 * du.used / du.total, 1) if du.total else 0}
    except OSError:
        scratch = None
    return {
        "nav": NAV,
        "drive": services.drive.state,
        "nas": services.nas.status,
        "nas_retry_seconds": services.config.nas.retry_seconds,
        "scratch": scratch,
        # Video Rip: the Disc being ripped (else the last one), and its live progress.
        "rip_disc": services.video_rip.disc,
        "rip_progress": services.video_rip.progress,
        "rip_failure": services.discs.unseen_failure(),
    }


def render_fragment(topic: str, services: Services) -> str:
    return TEMPLATES.get_template(FRAGMENTS[topic]).render(view_context(services))
