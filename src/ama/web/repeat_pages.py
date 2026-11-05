"""Repeat-Disc warning: the user's choice for an already-archived Disc."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response

from ama.repeat import Choice

router = APIRouter()


@router.post("/repeat/{choice}")
async def choose(request: Request, choice: Choice) -> Response:
    request.app.state.services.repeat.choose(choice)
    return RedirectResponse("/", status_code=303)
