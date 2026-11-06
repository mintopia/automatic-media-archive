"""Plex is asked to scan an archived folder at the path the Plex server sees it."""

from __future__ import annotations

from urllib.parse import parse_qs

import httpx

from ama.archive import Archive
from ama.config import Library, LibraryKind, PlexConfig
from ama.plex import Plex


def _scanned(tmp_path, libraries_path: str, folder) -> str:
    requests: list[httpx.Request] = []

    def handle(r: httpx.Request) -> httpx.Response:
        requests.append(r)
        return httpx.Response(200, json={"MediaContainer": {"Directory": [
            {"key": "1", "title": "Movies", "type": "movie"}]}})

    libraries = [Library(name="Movies", kind=LibraryKind.FILMS, path=str(tmp_path / "Films"),
                         plex="Movies", default=True),
                 Library(name="TV", kind=LibraryKind.TV, path=str(tmp_path / "TV"), default=True),
                 Library(name="Music", kind=LibraryKind.MUSIC, path=str(tmp_path / "Music"),
                         default=True)]
    plex = Plex(PlexConfig(url="http://plex:32400", token="t", libraries_path=libraries_path),
                httpx.Client(transport=httpx.MockTransport(handle)), Archive(libraries))
    plex.scan(folder)
    [scan] = [r for r in requests if "/refresh" in r.url.path]
    return parse_qs(scan.url.query.decode())["path"][0]


def test_plex_sees_each_library_folder_by_its_name_under_its_libraries_path(tmp_path):
    folder = tmp_path / "Films" / "Film (2001)"
    assert _scanned(tmp_path, "/volume1/media", folder) == "/volume1/media/Films/Film (2001)"


def test_without_a_libraries_path_plex_sees_the_folder_where_ama_does(tmp_path):
    folder = tmp_path / "Films" / "Film (2001)"
    assert _scanned(tmp_path, "", folder) == str(folder)
