"""Asking Plex Media Server to partially scan a folder just filed into the Archive.

Plex may run elsewhere (often on the NAS), so the folder is translated into the
server's own path (`plex.nas_path` replaces the Archive root), then matched to
the library whose folder contains it. The token goes in a header, never the URL.
"""

from __future__ import annotations

from pathlib import Path

import httpx

from ama.config import PlexConfig


class Plex:
    def __init__(self, cfg: PlexConfig, http: httpx.Client, archive_root: Path) -> None:
        self._cfg = cfg
        self._http = http
        self._root = archive_root

    def server_path(self, folder: Path) -> str:
        """`folder` (under the Archive root) as the Plex server sees it."""
        base = self._cfg.nas_path or str(self._root)
        sep = "/" if "/" in base else "\\"
        parts = folder.relative_to(self._root).parts
        return sep.join([base.rstrip("/\\"), *parts])

    def scan(self, folder: Path) -> str:
        """Start a partial scan of `folder`; a sentence for the Job log. Raises httpx.HTTPError."""
        if not (self._cfg.url and self._cfg.token):
            return "Plex isn't set up in ama.toml, so it will find this on its next scan"
        path = self.server_path(folder)
        base = self._cfg.url.rstrip("/")
        headers = {"X-Plex-Token": self._cfg.token, "Accept": "application/json"}
        r = self._http.get(f"{base}/library/sections", headers=headers)
        r.raise_for_status()
        section = _section_for(r.json(), path)
        if section is None:
            return f"No Plex library contains {path}, so Plex wasn't asked to scan it"
        url = f"{base}/library/sections/{section}/refresh"
        r = self._http.post(url, params={"path": path}, headers=headers)
        if r.status_code in (404, 405):  # older servers only take GET
            r = self._http.get(url, params={"path": path}, headers=headers)
        r.raise_for_status()
        return f"Asked Plex to scan {path}"


def _within(path: str, location: str) -> bool:
    if "\\" in location or ":" in location:  # a Windows server: case-insensitive
        path, location = path.casefold(), location.casefold()
    location = location.rstrip("/\\")
    return path == location or path.startswith((location + "/", location + "\\"))


def _section_for(sections: dict, path: str) -> str | None:
    for d in sections.get("MediaContainer", {}).get("Directory", []):
        if any(_within(path, loc.get("path", "")) for loc in d.get("Location", [])):
            return str(d["key"])
    return None
