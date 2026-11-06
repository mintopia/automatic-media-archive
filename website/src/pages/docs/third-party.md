---
layout: ../../layouts/Docs.astro
slug: third-party
description: The tools AMA uses, the licences they come under, and how each one reaches your PC.
---

AMA’s own code is free under the [MIT licence](https://github.com/mintopia/automatic-media-archive/blob/main/LICENSE). Everything else it uses is listed here, with its licence and how it gets to you. The same list is kept in the repository as [`THIRD_PARTY_NOTICES.md`](https://github.com/mintopia/automatic-media-archive/blob/main/THIRD_PARTY_NOTICES.md).

AMA doesn’t ship GPL or LGPL code itself. The GPL tools it runs are separate programs it downloads, and the Python libraries are installed from PyPI when you install AMA.

## How things reach you

<table class="kv">
  <thead><tr><th scope="col">Reaches you</th><th scope="col">What that means</th></tr></thead>
  <tbody>
    <tr><td>Installer</td><td>The Windows installer carries it, with its licence text beside it in the app folder.</td></tr>
    <tr><td>Installed by uv</td><td>The installer has uv download a pinned build while it installs. AMA doesn’t redistribute it.</td></tr>
    <tr><td>PyPI</td><td>Installed from PyPI with AMA. AMA doesn’t redistribute it.</td></tr>
    <tr><td>Downloaded</td><td>AMA downloads a pinned build the first time it starts and checks it against a known hash. AMA doesn’t redistribute it.</td></tr>
    <tr><td>Vendored</td><td>The file ships inside AMA, with its licence text next to it.</td></tr>
    <tr><td>You install it</td><td>You install it yourself. AMA never ships it.</td></tr>
  </tbody>
</table>

## Tools

The programs AMA runs, or that run AMA.

<table class="kv">
  <thead><tr><th scope="col">Tool</th><th scope="col">Licence</th><th scope="col">Reaches you</th></tr></thead>
  <tbody>
    <tr><td>MakeMKV</td><td>Proprietary</td><td>You install it<small>Reads DVDs and Blu-rays. <a href="https://www.makemkv.com">makemkv.com</a></small></td></tr>
    <tr><td>ffmpeg</td><td>GPL-3.0</td><td>Downloaded<small>Gyan’s “full” build, run as a separate program for Encodes. <a href="https://github.com/GyanD/codexffmpeg">Source</a></small></td></tr>
    <tr><td>cyanrip</td><td>GPL-3.0<small>Statically linked against libcdio and paranoia, also GPL-3.0.</small></td><td>Downloaded<small>AMA’s own build, run as a separate program for CD Rips. <a href="https://github.com/cyanreg/cyanrip">Source</a></small></td></tr>
    <tr><td>uv</td><td>MIT or Apache-2.0</td><td>Installer<small>Installs Python and AMA’s libraries. <a href="https://github.com/astral-sh/uv">Source</a></small></td></tr>
    <tr><td>Python</td><td>PSF-2.0</td><td>Installed by uv<small>A pinned CPython, inside the app folder. <a href="https://www.python.org">python.org</a></small></td></tr>
  </tbody>
</table>

## Python libraries

Every library AMA runs on, including the ones they need in turn. All come from PyPI, at the versions pinned in `uv.lock`.

<table class="kv">
  <thead><tr><th scope="col">Package</th><th scope="col">Licence</th><th scope="col">Needed by</th></tr></thead>
  <tbody>
    <tr><td>annotated-doc</td><td>MIT</td><td>fastapi</td></tr>
    <tr><td>annotated-types</td><td>MIT</td><td>pydantic</td></tr>
    <tr><td>anyio</td><td>MIT</td><td>starlette, httpx</td></tr>
    <tr><td>certifi</td><td>MPL-2.0</td><td>httpx</td></tr>
    <tr><td>click</td><td>BSD-3-Clause</td><td>uvicorn</td></tr>
    <tr><td>colorama</td><td>BSD-3-Clause</td><td>click (Windows)</td></tr>
    <tr><td>fastapi</td><td>MIT</td><td>AMA</td></tr>
    <tr><td>h11</td><td>MIT</td><td>uvicorn, httpcore</td></tr>
    <tr><td>httpcore</td><td>BSD-3-Clause</td><td>httpx</td></tr>
    <tr><td>httpx</td><td>BSD-3-Clause</td><td>AMA</td></tr>
    <tr><td>idna</td><td>BSD-3-Clause</td><td>anyio, httpx</td></tr>
    <tr><td>jinja2</td><td>BSD-3-Clause</td><td>AMA</td></tr>
    <tr><td>markupsafe</td><td>BSD-3-Clause</td><td>jinja2</td></tr>
    <tr><td>opentelemetry-api</td><td>Apache-2.0</td><td>fastapi</td></tr>
    <tr><td>pillow</td><td>MIT-CMU</td><td>AMA, pystray (Windows)</td></tr>
    <tr><td>pydantic</td><td>MIT</td><td>fastapi</td></tr>
    <tr><td>pydantic-core</td><td>MIT</td><td>pydantic</td></tr>
    <tr><td>pystray</td><td>LGPL-3.0</td><td>AMA (Windows tray)<small>AMA only imports it, and it’s installed from PyPI rather than bundled.</small></td></tr>
    <tr><td>python-multipart</td><td>Apache-2.0</td><td>AMA</td></tr>
    <tr><td>six</td><td>MIT</td><td>pystray</td></tr>
    <tr><td>starlette</td><td>BSD-3-Clause</td><td>fastapi</td></tr>
    <tr><td>tomlkit</td><td>MIT</td><td>AMA</td></tr>
    <tr><td>typing-extensions</td><td>PSF-2.0</td><td>pydantic, anyio, fastapi</td></tr>
    <tr><td>typing-inspection</td><td>MIT</td><td>pydantic, fastapi</td></tr>
    <tr><td>uvicorn</td><td>BSD-3-Clause</td><td>AMA</td></tr>
  </tbody>
</table>

## Files inside AMA

Shipped as part of AMA’s web UI, each with its licence text beside it.

<table class="kv">
  <thead><tr><th scope="col">File</th><th scope="col">Licence</th><th scope="col">What it is</th></tr></thead>
  <tbody>
    <tr><td>htmx</td><td>0BSD</td><td>Keeps the pages up to date (version 2.0.4)</td></tr>
    <tr><td>htmx SSE extension</td><td>0BSD</td><td>Live updates from AMA</td></tr>
    <tr><td>Archivo</td><td>OFL-1.1</td><td>The typeface: Archivo and Archivo Narrow</td></tr>
  </tbody>
</table>

## Services

AMA also asks these online services about your Discs. They aren’t software AMA ships, but their terms apply to what you look up:

- **[TMDB](https://www.themoviedb.org/)** identifies films and TV series, with your own API key. AMA uses the TMDB API but is not endorsed or certified by TMDB.
- **[MusicBrainz](https://musicbrainz.org/)** identifies CDs, and the **[Cover Art Archive](https://coverartarchive.org/)** supplies their covers.
- **AccurateRip** checks each CD Track against other people’s rips of the same CD.
