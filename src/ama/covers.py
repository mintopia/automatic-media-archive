"""Cover art and posters, cached next to the state DB (`<state_db dir>/covers/`).

Shown while a Disc rips and on its History page, so a filed Disc's page never
needs scratch or a live web request. Files are named by source and id
(`release-<MusicBrainz id>.jpg`, `tmdb-movie-<id>.jpg`, `tmdb-tv-<id>.jpg`) and
written temp name -> rename, so a half-written image is never served.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from ama.musicbrainz import MusicBrainz, Release

DIR = "covers"
_NAME = re.compile(r"^[a-z]+(?:-[a-z]+)?-[0-9a-f-]+\.(?:jpg|png)$")


class Covers:
    def __init__(self, folder: Path, mb: MusicBrainz) -> None:
        self.folder = folder
        self._mb = mb

    def path(self, name: str) -> Path | None:
        """The cached image called `name`, or None (also for any name we wouldn't write)."""
        if not _NAME.match(name):
            return None
        p = self.folder / name
        return p if p.is_file() else None

    def store(self, stem: str, data: bytes, ext: str) -> str:
        """Cache an image; its file name (idempotent)."""
        self.folder.mkdir(parents=True, exist_ok=True)
        name = f"{stem}.{ext}"
        tmp = self.folder / f"{name}.tmp"
        tmp.write_bytes(data)
        os.replace(tmp, self.folder / name)
        return name

    def cached(self, stem: str) -> str | None:
        return next((f"{stem}.{ext}" for ext in ("jpg", "png")
                     if (self.folder / f"{stem}.{ext}").is_file()), None)

    def release(self, release: Release) -> str | None:
        """The release's front cover from the Cover Art Archive, cached: its file name, or
        None if it has none. Raises httpx.HTTPError when the archive can't be reached."""
        stem = f"release-{release.id}"
        name = self.cached(stem)
        if name is None:
            art = self._mb.cover_art(release)
            if art is None:
                return None
            name = self.store(stem, *art)
        return name
