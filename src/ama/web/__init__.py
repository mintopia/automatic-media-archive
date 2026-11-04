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

from ama.tools import NEEDED_FOR, ToolDownloading, ToolFailed

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
    "tools": "partials/tools.html",
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
        **_tools_context(services),
    }


def _tools_context(services: Services) -> dict[str, Any]:
    tools = services.tools
    managed = []
    for pin in tools.pins:
        for m in pin.members:
            st = tools.status(m.name)
            if isinstance(st, ToolDownloading | ToolFailed):
                managed.append({"status": st, "needed_for": NEEDED_FOR[m.name]})
                break
    return {"tools": managed, "makemkv": tools.status("makemkvcon"),
            "retry_seconds": tools.retry_seconds}


def render_fragment(topic: str, services: Services) -> str:
    return TEMPLATES.get_template(FRAGMENTS[topic]).render(view_context(services))
