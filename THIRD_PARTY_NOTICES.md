# Third-party notices

AMA's own code is MIT-licensed (see `LICENSE`). This file lists everything else AMA uses, its licence, and how it reaches you ([ADR 0012](docs/decisions/0012-mit-licence-with-third-party-notices.md)):

- **PyPI**: the package manager installs it from PyPI with AMA. AMA does not redistribute it.
- **Downloaded**: AMA downloads a pinned, hash-checked build at runtime (ADR 0006, 0007). AMA does not redistribute it.
- **Vendored**: the file ships inside AMA, with its licence text next to it.
- **User-installed**: you install it yourself. AMA never ships it.

A new dependency needs a new row here, and a GPL dependency cannot be added.

## Python packages

Every runtime dependency in `uv.lock`, direct and transitive. Exact versions are pinned in `uv.lock`.

| Package | Licence | Reaches you | Required by |
|---|---|---|---|
| annotated-doc | MIT | PyPI | fastapi |
| annotated-types | MIT | PyPI | pydantic |
| anyio | MIT | PyPI | starlette, httpx |
| certifi | MPL-2.0 | PyPI | httpx |
| click | BSD-3-Clause | PyPI | uvicorn |
| colorama | BSD-3-Clause | PyPI | click (Windows) |
| fastapi | MIT | PyPI | AMA |
| h11 | MIT | PyPI | uvicorn, httpcore |
| httpcore | BSD-3-Clause | PyPI | httpx |
| httpx | BSD-3-Clause | PyPI | AMA |
| idna | BSD-3-Clause | PyPI | anyio, httpx |
| jinja2 | BSD-3-Clause | PyPI | AMA |
| markupsafe | BSD-3-Clause | PyPI | jinja2 |
| opentelemetry-api | Apache-2.0 | PyPI | fastapi |
| pillow | MIT-CMU | PyPI | AMA, pystray (Windows) |
| pydantic | MIT | PyPI | fastapi |
| pydantic-core | MIT | PyPI | pydantic |
| pystray | LGPL-3.0 | PyPI | AMA (Windows tray) |
| python-multipart | Apache-2.0 | PyPI | AMA |
| six | MIT | PyPI | pystray |
| starlette | BSD-3-Clause | PyPI | fastapi |
| tomlkit | MIT | PyPI | AMA |
| typing-extensions | PSF-2.0 | PyPI | pydantic, anyio, fastapi |
| typing-inspection | MIT | PyPI | pydantic, fastapi |
| uvicorn | BSD-3-Clause | PyPI | AMA |

pystray is LGPL-3.0. AMA only imports it, and it is installed from PyPI rather than bundled, so AMA redistributes no LGPL code.

## External tools

| Tool | Licence | Reaches you | Source |
|---|---|---|---|
| ffmpeg | GPL-3.0 | Downloaded (Gyan "full" build, run as a separate program) | https://github.com/GyanD/codexffmpeg |
| cyanrip | GPL-3.0 (statically linked against GPL-3.0 libcdio/paranoia) | Downloaded (AMA's own build, run as a separate program) | https://github.com/cyanreg/cyanrip |
| MakeMKV | Proprietary | User-installed | https://www.makemkv.com |

## Vendored files

| File | Licence | Reaches you | Licence text |
|---|---|---|---|
| htmx | 0BSD | Vendored (`src/ama/web/static/vendor/htmx.min.js`, 2.0.4) | `src/ama/web/static/vendor/LICENSE-htmx.txt` |
| htmx SSE extension | 0BSD | Vendored (`src/ama/web/static/vendor/htmx-ext-sse.js`) | `src/ama/web/static/vendor/LICENSE-htmx.txt` |
| Archivo | OFL-1.1 | Vendored (`src/ama/web/static/fonts/archivo-*.woff2`, Archivo and Archivo Narrow) | `src/ama/web/static/fonts/OFL-Archivo.txt` |
