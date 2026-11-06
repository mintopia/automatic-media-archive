# Decision: AMA is MIT-licensed, with third-party notices

Status: accepted
Date: 2026-11-06

## Context
AMA is going public on GitHub and needs a licence. Not everything it uses is permissive:

- **mutagen** (GPL-2.0-or-later) is imported directly by the CD archiver.
- **pystray** (LGPL-3.0) runs the Windows tray.
- **ffmpeg** (Gyan "full" build, GPL-3.0) and AMA's own **cyanrip** build (statically linked against GPL-3.0 libcdio/paranoia) are separate programs that AMA downloads at runtime. They are pinned and hash-checked, and never vendored (ADR 0006, 0007).
- **MakeMKV** is proprietary. The user installs it, and AMA never ships it.
- The vendored **htmx** and its SSE extension (0BSD) and the **Archivo** fonts (OFL-1.1) live in `src/`.

## Decision
- AMA's own code is MIT, © 2026 Jessica Smith: there is a `LICENSE` file and `license = "MIT"` in `pyproject.toml`.
- **mutagen is removed.** AMA used it only to replace a FLAC's Vorbis comments. AMA's own small FLAC tag writer now rewrites the `VORBIS_COMMENT` block, reusing `PADDING`, and never touches the audio frames.
- The Windows installer (ADR 0017) carries only `uv` (MIT/Apache-2.0) and AMA's wheel. pystray and the other dependencies are installed from PyPI at install time, and ffmpeg/cyanrip are downloaded at runtime. AMA therefore redistributes no GPL or LGPL code.
- `THIRD_PARTY_NOTICES.md` lists every dependency and external tool with its licence and how it reaches the user (installed by the package manager, downloaded at runtime, vendored, or user-installed).
- The licence texts of the vendored files (htmx 0BSD, Archivo OFL) ship next to them.

## Consequences
- Anyone may reuse AMA's code under MIT.
- AMA owns FLAC tag writing, so it needs round-trip tests against real cyanrip output.
- A new dependency means a new line in `THIRD_PARTY_NOTICES.md`, and **a GPL dependency cannot be added**. Neither can a switch to a frozen/bundled installer that would redistribute LGPL code, unless this ADR is revisited first.

## Supersedes
None
