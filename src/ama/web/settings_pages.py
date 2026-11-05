"""Settings routes: one page per section, each saving its own keys to ama.toml (ADR 0008).

GET shows what's in the file now (re-read on every view, so a hand edit shows
at once). POST validates through the config models and writes the file
(`ama.settings`); a rejected save re-renders with field messages and leaves
the file alone. Saved secrets are never sent to the browser: a secret field
posts its key only to replace it, and `remove=<key>` to empty it.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, get_origin

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from ama.config import ConfigError
from ama.notify import webhook
from ama.tools import ToolUnavailable
from ama.settings import SettingsRejected, field_info, is_secret, raw_at, value_at
from ama.web import TEMPLATES, view_context
from ama.web.settings_sections import (BY_SLUG, SECTIONS, TABS, Choice, Field, Group, Option,
                                       PerType, Section, Status, first_of, label_of)

if TYPE_CHECKING:
    from ama.app import Services

router = APIRouter()


@dataclass
class FieldView:
    key: str
    id: str
    label: str  # as the error summary names it ("Quality and size, DVD")
    kind: str  # "text" | "number" | "secret" | "choice"
    step: str
    value: str  # never a saved secret
    is_set: bool = False  # secrets: whether the file holds one
    error: str = ""
    pending: bool = False  # saved, waiting for a restart


@dataclass
class RowView:
    row: Field | PerType | Choice
    fields: list[FieldView]
    placeholder: str = ""
    status: Status | None = None
    options: tuple[Option, ...] = ()  # a Choice's
    selects: list[tuple[FieldView, tuple[Option, ...]]] = field(default_factory=list)  # PerType

    @property
    def choice(self) -> bool:
        return isinstance(self.row, Choice)

    @property
    def pertype(self) -> bool:
        return isinstance(self.row, PerType)

    @property
    def id(self) -> str:
        return self.row.id if isinstance(self.row, PerType) else self.fields[0].id

    @property
    def pending(self) -> bool:
        return any(f.pending for f in self.fields)

    @property
    def errors(self) -> list[FieldView]:
        return [f for f in [*self.fields, *(s for s, _ in self.selects)] if f.error]

    @property
    def cells(self) -> list[tuple[str, FieldView, tuple[FieldView, tuple[Option, ...]] | None]]:
        """A per-Disc-Type table's rows: (Disc Type name, its field, its select if any)."""
        assert isinstance(self.row, PerType)
        selects: list = self.selects or [None] * len(self.fields)
        return [(name, f, s) for (name, _), f, s in
                zip(self.row.rows, self.fields, selects, strict=True)]


@dataclass
class GroupView:
    group: Group
    rows: list[RowView]
    status: Status | None = None
    open: bool = False  # an Advanced disclosure starts open when it holds an error
    summary: str = ""  # an untagged disclosure's line of saved values


@dataclass
class PageView:
    section: Section
    groups: list[GroupView] = field(default_factory=list)
    errors: list[FieldView] = field(default_factory=list)
    general: list[str] = field(default_factory=list)


def _id(key: str) -> str:
    return key.replace(".", "-")


def _kind(key: str) -> tuple[str, str]:
    if is_secret(key):
        return "secret", ""
    ann = field_info(key).annotation
    if get_origin(ann) is Literal:
        return "choice", ""
    if ann is int:
        return "number", "1"
    if ann is float:
        return "number", "any"
    return "text", ""


def _shown(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return "" if value is None else str(value)


def _page(services: Services, section: Section, posted: dict[str, str] | None = None,
          rejected: SettingsRejected | None = None) -> PageView:
    settings = services.settings
    assert settings is not None and settings.file is not None
    raw, cfg = settings.file.values()
    pending = set(settings.pending())
    errors = rejected.errors if rejected else {}
    view = PageView(section, general=list(rejected.general) if rejected else [])

    def field_view(key: str, label: str, choice: bool = False) -> FieldView:
        """A typed box shows the file as written; a choice shows the value it means ("f" is F:)."""
        kind, step = _kind(key)
        if kind == "secret":
            value = ""
        elif posted is not None and key in posted:
            value = posted[key]
        else:
            in_file = None if choice else raw_at(raw, key)
            value = _shown(value_at(cfg, key) if in_file is None else in_file)
        return FieldView(key, _id(key), label, kind, step, value,
                         is_set=kind == "secret" and bool(value_at(cfg, key)),
                         error=errors.get(key, ""), pending=key in pending)

    for g in section.groups:
        rows = []
        for r in g.rows:
            options: tuple[Option, ...] = ()
            selects = []
            if isinstance(r, PerType):
                fields = [field_view(k, f"{r.label}, {name}") for name, k in r.rows]
                selects = [(field_view(k, f"{r.select_column}, {name}"), opts)
                           for (name, _), (k, opts) in zip(r.rows, r.selects, strict=False)]
            else:
                fields = [field_view(r.key, r.label, choice=isinstance(r, Choice))]
            placeholder = ""
            status = None
            if isinstance(r, Field):
                placeholder = r.placeholder(services) if callable(r.placeholder) else r.placeholder
                status = r.status(services) if r.status else None
            if isinstance(r, Choice):
                saved = _shown(value_at(cfg, r.key))
                options = r.options(services, saved) if callable(r.options) else r.options
            rows.append(RowView(r, fields, placeholder, status, options, selects))
        gv = GroupView(g, rows, g.status(services) if g.status else None,
                       summary=g.summary(cfg) if g.summary else "")
        gv.open = any(rv.errors for rv in rows)
        view.groups.append(gv)
        view.errors += [f for rv in rows for f in rv.errors]
    return view


def _context(request: Request, services: Services, section: Section, **extra: Any) -> dict:
    settings = services.settings
    assert settings is not None
    pending = settings.pending()
    new_address = ""
    if "web.port" in pending:
        new_address = f"{request.url.scheme}://{request.url.hostname}:{settings.saved.web.port}"
    return view_context(services) | {
        "current": "/settings",
        "section": section,
        "tabs": [(label, f"/settings/{first_of(key).slug}", key == section.tab)
                 for key, label in TABS],
        "subs": [s for s in SECTIONS if s.tab == section.tab] if section.sub else [],
        "pending": [label_of(k) for k in pending],
        "new_address": new_address,
        "busy": services.restart.busy() if pending or services.restart.waiting else None,
        "restart_waiting": services.restart.waiting,
        "back": f"/settings/{section.slug}",
        "confirm": False,
        "problem": settings.problem,
        "page": None,
        "saved": "",
        "rejected": False,
        **extra,
    }


def _section(slug: str) -> Section:
    section = BY_SLUG.get(slug)
    if section is None:
        raise HTTPException(404)
    return section


def _render(request: Request, ctx: dict, status: int = 200) -> Response:
    return TEMPLATES.TemplateResponse(request, "settings.html", ctx, status_code=status)


def _check(services: Services, section: Section, changes: dict[str, str]) -> None:
    """Choices the config model allows but this PC doesn't (an encoder that failed its
    test encode). Raises SettingsRejected; the file is untouched."""
    settings = services.settings
    assert settings is not None and settings.file is not None
    _, saved = settings.file.values()
    errors = {}
    for g in section.groups:
        for r in g.rows:
            if isinstance(r, Choice) and r.check and r.key in changes:
                why = r.check(services, changes[r.key], _shown(value_at(saved, r.key)))
                if why:
                    errors[r.key] = why
    if errors:
        raise SettingsRejected(errors, [])


def render_section(request: Request, services: Services, slug: str, status: int = 200,
                   **extra: Any) -> Response:
    """The section's page as GET shows it, with `extra` in place of the usual context
    (a section's own routes use it to re-render a rejected edit)."""
    section = _section(slug)
    try:
        page = _page(services, section)
    except ConfigError as e:
        return _render(request, _context(request, services, section, problem=str(e)), status)
    if section.context and not set(extra) & {"problem"}:
        extra = section.context(services, request) | extra
    return _render(request, _context(request, services, section, page=page, **extra), status)


@router.get("/settings")
def settings_home() -> Response:
    return RedirectResponse(f"/settings/{SECTIONS[0].slug}", status_code=303)


@router.get("/settings/{slug:path}", response_class=HTMLResponse)
def settings_page(request: Request, slug: str, saved: str = "", restart: str = "") -> Response:
    services: Services = request.app.state.services
    section = _section(slug)
    if services.settings is None or services.settings.file is None:
        return _render(request, _context(request, services, section,
                                         problem="AMA wasn't started from a config file."))
    services.settings.refresh()
    return render_section(request, services, slug, saved=saved,
                          confirm=restart == "confirm")


@router.post("/settings/archive/encode/test-encoders")
async def test_encoders(request: Request) -> Response:
    """"Test encoders again": test every encoder now, then show the results."""
    services: Services = request.app.state.services
    try:
        await services.encoders.probe_all()
    except ToolUnavailable:
        pass  # ffmpeg isn't ready; the background test runs once it is
    return RedirectResponse("/settings/archive/encode", status_code=303)


@router.post("/settings/alerts/webhook-test", response_class=HTMLResponse)
async def webhook_test(request: Request) -> Response:
    """"Send test": post a test event to the saved webhook and say how it went."""
    services: Services = request.app.state.services
    if services.settings is None or services.settings.file is None:
        raise HTTPException(409, "AMA wasn't started from a config file")
    hook = webhook(services.config, services.http)
    if hook is None:
        result = Status("Save a webhook URL first, then send a test.", ok=False)
    elif (why := await asyncio.to_thread(hook.send_test)) is None:
        result = Status("Test alert sent")
    else:
        result = Status(f"Couldn't send the test alert: {why}", ok=False)
    return render_section(request, services, "alerts", webhook_test=result)


@router.post("/settings/{slug:path}", response_class=HTMLResponse)
async def settings_save(request: Request, slug: str) -> Response:
    services: Services = request.app.state.services
    section = _section(slug)
    settings = services.settings
    if settings is None or settings.file is None:
        raise HTTPException(409, "AMA wasn't started from a config file")
    form = await request.form()
    removed = set(form.getlist("remove"))
    changes: dict[str, str] = {}
    for key in section.field_keys():
        typed = form.get(key)
        if is_secret(key):
            if key in removed:
                changes[key] = ""
            elif isinstance(typed, str) and typed:
                changes[key] = typed
        elif isinstance(typed, str):
            changes[key] = typed.strip()
    try:
        _check(services, section, changes)
        settings.save(changes)
    except SettingsRejected as e:
        posted = {k: v for k, v in changes.items() if not is_secret(k)}
        page = _page(services, section, posted, e)
        return _render(request, _context(request, services, section, page=page, rejected=True),
                       status=422)
    except ConfigError as e:
        return _render(request, _context(request, services, section, problem=str(e)), 422)
    after = form.get("next")  # "Save and go" from the leave guard: another section
    if isinstance(after, str) and after.removeprefix("/settings/") in BY_SLUG:
        return RedirectResponse(after, status_code=303)
    return RedirectResponse(f"/settings/{section.slug}?saved={datetime.now():%H:%M}",
                            status_code=303)
