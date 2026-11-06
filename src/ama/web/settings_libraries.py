"""Settings › Archive › Libraries: the Libraries grouped by kind (DESIGN.md "Settings Page ›
Libraries"), each added, edited, made default or removed on its own.

The page is server-rendered: `?add=<kind>`, `?edit=<name>` and `?remove=<name>` open the
inline form or confirm, and `?focus=<name>` puts focus back on a row after Cancel. The
POSTs write ama.toml through `Settings` (ADR 0008) and land back on the page; a rejected
one re-renders with the form open and its messages. A kind with Naming Patterns
(`naming.patterns`) gets a pattern editor for each in its form, whose preview (`GET …/pattern`)
redraws as the pattern is typed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from markupsafe import Markup

from ama import naming
from ama.config import ConfigError, LibraryKind, Library
from ama.settings import SettingsRejected
from ama.web import TEMPLATES

if TYPE_CHECKING:
    from ama.app import Services

router = APIRouter()

SLUG = "archive/libraries"
PAGE = f"/settings/{SLUG}"
_TYPE_WORD = {LibraryKind.FILMS: "movie", LibraryKind.TV: "TV", LibraryKind.MUSIC: "music"}


@dataclass
class Form:
    """The open Add or Edit form."""

    kind: LibraryKind
    original: str | None  # None = a new Library
    name: str = ""
    plex: str = ""
    path: str = ""
    # Each pattern key's pattern as typed (`naming.patterns`); the defaults for a new Library.
    patterns: dict[str, str] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def naming(self) -> list[PatternView]:
        """A pattern editor for each of the kind's patterns."""
        return [view for key in naming.patterns(self.kind)
                if (view := pattern_view(self.kind, self.patterns.get(key, ""), key))]


@dataclass(frozen=True)
class PatternView:
    """The Naming Pattern editor: the pattern, its check and preview, and what it can use."""

    key: str  # the Library key it is saved to
    title: str  # the editor's label
    pattern: str
    check: naming.Check
    preview: str  # the name it gives the examples; "" when the pattern can't be used
    fields: tuple[naming.Field, ...]
    presets: tuple[naming.Preset, ...]


def pattern_view(kind: LibraryKind, pattern: str, key: str = "pattern") -> PatternView | None:
    """The editor for the pattern in a `kind` Library's `key`; None if it has no such key."""
    nk = naming.patterns(kind).get(key)
    if nk is None:
        return None
    check = naming.check(pattern, nk)
    preview = "" if check.errors else naming.render(
        pattern, nk, naming.examples(nk), naming.EXTENSIONS[nk]).as_posix()
    label = naming.label(nk)
    title = "Naming pattern" if label == "pattern" else label.capitalize()
    return PatternView(key, title, pattern, check, preview, naming.FIELDS[nk],
                       naming.PRESETS.get(nk, ()))


def _patterns_of(lib: Library) -> dict[str, str]:
    return {key: naming.pattern_of(lib, nk) for key, nk in naming.patterns(lib.kind).items()}


def _new_patterns(kind: LibraryKind) -> dict[str, str]:
    return {key: naming.DEFAULTS[nk] for key, nk in naming.patterns(kind).items()}


@dataclass
class Row:
    lib: Library
    id: str
    form: Form | None = None
    removing: bool = False
    focus: bool = False  # Cancel put focus back here (its Remove, or Edit on a default)


@dataclass
class KindGroup:
    kind: LibraryKind
    default: Library
    rows: list[Row]
    adding: Form | None = None


@dataclass
class LibrariesView:
    groups: list[KindGroup]
    plex: list[dict] | None  # Plex's libraries; None = not set up or unreachable
    plex_url: str
    problems: list[str] = field(default_factory=list)

    def options(self, form: Form) -> list[str]:
        """The Plex libraries the form's list offers: only those of its kind's type."""
        from ama.plex import PLEX_TYPE
        names = [d.get("title", "") for d in self.plex or []
                 if d.get("type") == PLEX_TYPE[form.kind]]
        if form.plex and form.plex not in names:
            names.append(form.plex)  # keep a pick Plex doesn't list (any more)
        return names

    def plex_hint(self, form: Form) -> Markup:
        if self.plex is None:
            where = f"at {self.plex_url}" if self.plex_url else "(it isn't set up)"
            return Markup(
                "AMA couldn't reach Plex {}. Save without one and Plex finds this folder on "
                "its next scheduled scan; pick one here once Plex is back. "
                '<a href="#plex-url">Check the Plex connection</a>').format(where)
        return Markup("Plex's {} libraries. Plex scans this folder after each Job is filed "
                      "here.").format(_TYPE_WORD[form.kind])


def libraries_view(services: Services, query: Mapping[str, str],
                   form: Form | None = None, problems: list[str] | None = None) -> LibrariesView:
    """What the Libraries partial shows. `form` is a rejected form to show again."""
    settings = services.settings
    assert settings is not None and settings.file is not None
    _, cfg = settings.file.values()
    libraries = cfg.libraries
    if form is None:
        if (add := query.get("add")) in {k.value for k in LibraryKind}:
            form = Form(LibraryKind(add), None, patterns=_new_patterns(LibraryKind(add)))
        elif (lib := _named(libraries, query.get("edit"))) is not None:
            form = Form(lib.kind, lib.name, lib.name, lib.plex, lib.path, _patterns_of(lib))
    removing = _named(libraries, query.get("remove"))
    if removing is not None and removing.default:
        removing = None
    groups = []
    for kind in LibraryKind:
        ofkind = sorted((lib for lib in libraries if lib.kind == kind),
                        key=lambda lib: not lib.default)  # stable: file order otherwise
        rows = [Row(lib, f"lib-{libraries.index(lib)}",
                    form if form and form.original == lib.name else None,
                    removing is lib, query.get("focus") == lib.name) for lib in ofkind]
        adding = form if form and form.original is None and form.kind == kind else None
        groups.append(KindGroup(kind, next(r.lib for r in rows if r.lib.default), rows, adding))
    return LibrariesView(groups, services.plex.listing(), cfg.plex.url, problems or [])


def _named(libraries: tuple[Library, ...], name: str | None) -> Library | None:
    return next((lib for lib in libraries if name and lib.name == name), None)


@router.post(PAGE + "/{action}")
async def libraries_save(request: Request, action: str) -> Response:
    from ama.web.settings_pages import render_section
    services: Services = request.app.state.services
    settings = services.settings
    if settings is None or settings.file is None:
        raise HTTPException(409, "AMA wasn't started from a config file")
    form = {k: v for k, v in (await request.form()).items() if isinstance(v, str)}
    name = form.get("library", "")
    focus = name
    shown: Form | None = None
    try:
        match action:
            case "save":
                try:
                    kind = LibraryKind(form.get("lib.kind", ""))
                except ValueError:
                    raise HTTPException(400, "Unknown kind of Library") from None
                original = form.get("lib.original") or None
                typed = {k: form[f"lib.{k}"] for k in ("name", "plex", "path", *naming.KEYS)
                         if f"lib.{k}" in form}
                shown = Form(kind, original, typed.get("name", ""), typed.get("plex", ""),
                             typed.get("path", ""),
                             {k: typed.get(k, "") for k in naming.patterns(kind)})
                settings.save_library(kind, original, typed)
                focus = typed.get("name", "").strip()
            case "default":
                settings.make_default(name)
            case "remove":
                settings.remove_library(name)
                focus = ""
            case _:
                raise HTTPException(404)
    except SettingsRejected as e:
        if shown is not None:
            shown.errors = dict(e.errors)
        view = libraries_view(services, {}, shown, list(e.general))
        return render_section(request, services, SLUG, libraries=view, status=422)
    except ConfigError as e:
        return render_section(request, services, SLUG, problem=str(e), status=422)
    return RedirectResponse(PAGE + (f"?focus={quote(focus)}" if focus else ""), status_code=303)


@router.get(PAGE + "/pattern", response_class=HTMLResponse)
def pattern_preview(request: Request) -> Response:
    """The pattern editor's preview, errors and warnings for the pattern as typed in
    `lib.<key>` (`key` defaults to "pattern")."""
    try:
        kind = LibraryKind(request.query_params.get("lib.kind", ""))
    except ValueError:
        raise HTTPException(400, "Unknown kind of Library") from None
    key = request.query_params.get("key", "pattern")
    view = pattern_view(kind, request.query_params.get(f"lib.{key}", ""), key)
    if view is None:
        raise HTTPException(404, f"{kind.label} Libraries have no pattern")
    return TEMPLATES.TemplateResponse(request, "partials/naming_check.html", {"pv": view})


def context(services: Services, request: Request) -> dict[str, Any]:
    """The Libraries partial's context for a GET of the page."""
    return {"libraries": libraries_view(services, dict(request.query_params))}
