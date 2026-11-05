"""Asking Plex Media Server to partially scan a folder just filed into the Archive.

Plex may run elsewhere (often on the NAS), so the folder is translated into the
server's own path (`plex.nas_path` replaces the Archive root). The scan goes to
the Plex library of the Library the folder is in (`Library.plex`, by name), or,
when that Library names none, to the Plex library whose folder contains it. The
token goes in a header, never the URL.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from ama.config import Kind, PlexConfig
from ama.problems import Problem, Problems

if TYPE_CHECKING:
    from ama.archive import Archive

# The Plex library type that holds each kind.
PLEX_TYPE = {Kind.FILMS: "movie", Kind.TV: "show", Kind.MUSIC: "artist"}


class Plex:
    def __init__(self, cfg: PlexConfig, http: httpx.Client, archive: Archive,
                 problems: Problems | None = None) -> None:
        self.cfg = cfg
        self._problems = problems
        self._http = http
        self._archive = archive
        self._listed: tuple[tuple[str, str], float, list[dict] | None] | None = None

    @property
    def configured(self) -> bool:
        return bool(self.cfg.url and self.cfg.token)

    def server_path(self, folder: Path) -> str:
        """`folder` (under the Archive root) as the Plex server sees it."""
        root = self._archive.root
        base = self.cfg.nas_path or str(root)
        sep = "/" if "/" in base else "\\"
        parts = folder.relative_to(root).parts
        return sep.join([base.rstrip("/\\"), *parts])

    def _get(self, path: str, timeout: float | None = None, **params: str) -> httpx.Response:
        headers = {"X-Plex-Token": self.cfg.token, "Accept": "application/json"}
        r = self._http.get(f"{self.cfg.url.rstrip('/')}{path}", params=params or None,
                           headers=headers,
                           **({"timeout": timeout} if timeout is not None else {}))
        r.raise_for_status()
        return r

    def listing(self, timeout: float = 3.0, ttl: float = 10.0) -> list[dict] | None:
        """Plex's libraries for Settings, or None when Plex isn't set up or can't be reached.
        Remembered for `ttl` seconds, so one page view asks Plex once."""
        if not self.configured:
            return None
        key = (self.cfg.url, self.cfg.token)
        if self._listed and self._listed[0] == key and time.monotonic() - self._listed[1] < ttl:
            return self._listed[2]
        try:
            found: list[dict] | None = _directories(
                self._get("/library/sections", timeout).json())
        except (httpx.HTTPError, ValueError):
            found = None
        self._listed = (key, time.monotonic(), found)
        return found

    def libraries(self, kind: Kind) -> list[str] | None:
        """The names of Plex's libraries that can hold `kind`; None as for `listing`."""
        found = self.listing()
        if found is None:
            return None
        return [d.get("title", "") for d in found if d.get("type") == PLEX_TYPE[kind]]

    def scan(self, folder: Path) -> str:
        """Start a partial scan of `folder`; a sentence for the Disc log. Raises httpx.HTTPError,
        and shows a banner until a scan works again."""
        try:
            said = self._scan(folder)
        except httpx.HTTPError as e:
            if self._problems is not None:
                self._problems.report(Problem.PLEX, _why(e))
            raise
        if self._problems is not None:
            self._problems.resolved(Problem.PLEX)
        return said

    def _scan(self, folder: Path) -> str:
        if not self.configured:
            return "Plex isn't set up in ama.toml, so it will find this on its next scan"
        path = self.server_path(folder)
        sections = self._get("/library/sections").json()
        library = self._archive.library_of(folder)
        if library is not None and library.plex:
            section = _section_named(sections, library.plex)
            if section is None:
                return (f"Plex has no library called {library.plex}, so Plex wasn't asked to "
                        f"scan {path}")
        else:
            section = _section_for(sections, path)
            if section is None:
                return f"No Plex library contains {path}, so Plex wasn't asked to scan it"
        headers = {"X-Plex-Token": self.cfg.token, "Accept": "application/json"}
        url = f"{self.cfg.url.rstrip('/')}/library/sections/{section}/refresh"
        r = self._http.post(url, params={"path": path}, headers=headers)
        if r.status_code in (404, 405):  # older servers only take GET
            r = self._http.get(url, params={"path": path}, headers=headers)
        r.raise_for_status()
        return f"Asked Plex to scan {path}"


def _directories(sections: dict) -> list[dict]:
    return sections.get("MediaContainer", {}).get("Directory", [])


def _within(path: str, location: str) -> bool:
    if "\\" in location or ":" in location:  # a Windows server: case-insensitive
        path, location = path.casefold(), location.casefold()
    location = location.rstrip("/\\")
    return path == location or path.startswith((location + "/", location + "\\"))


def _section_named(sections: dict, title: str) -> str | None:
    return next((str(d["key"]) for d in _directories(sections) if d.get("title") == title),
                None)


def _section_for(sections: dict, path: str) -> str | None:
    for d in _directories(sections):
        if any(_within(path, loc.get("path", "")) for loc in d.get("Location", [])):
            return str(d["key"])
    return None


def _why(e: httpx.HTTPError) -> str:
    """A failure without the request (its URL could name the server's private address)."""
    if isinstance(e, httpx.HTTPStatusError):
        return f"HTTP {e.response.status_code}"
    return type(e).__name__
