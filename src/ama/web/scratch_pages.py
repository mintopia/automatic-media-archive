"""The scratch page: how full scratch is, the Disc refused for lack of space, and what holds it."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from ama.web import TEMPLATES, view_context

router = APIRouter()


@router.get("/scratch", response_class=HTMLResponse)
def scratch_page(request: Request) -> Response:
    services = request.app.state.services
    ctx = view_context(services) | {"current": "/"}
    return TEMPLATES.TemplateResponse(request, "scratch.html", ctx)
