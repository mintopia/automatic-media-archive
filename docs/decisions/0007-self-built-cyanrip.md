# Decision: AMA builds its own cyanrip from a pinned upstream commit

Status: accepted
Date: 2026-11-04

## Context
ADR 0006 pins AMA's cyanrip. The latest tagged release, v0.9.3.1 (2024-06), has two bugs that hit AMA on Windows:

- **AccurateRip lookups fail for about half of all Discs** (cyanrip #145). The CDDB ID is parsed with `strtol`, which saturates at `0x7FFFFFFF` on Windows (32-bit `long`), so every Disc whose CDDB ID is `0x80000000` or more asks for the wrong database entry and comes back "not found". ADR 0004 sends those Discs to Review, so half of all CDs would need a person for no reason.
- **Absolute paths in `-D` lose their drive letter** (cyanrip #109): the `:` is sanitised into a lookalike character. AMA works around it by running cyanrip from inside the scratch folder.

Upstream master fixes both, but there has been no release since. The nightly Windows builds are deleted after a while, so a pin to one would break, and we couldn't rebuild it.

## Decision
- AMA builds cyanrip itself from upstream commit **`648b1dddd265cfd2bb69483a826eb5a5c7e7079e`** (master, 2026-10-26, version `0.9.4-rc3`). `-v` prints `cyanrip 0.9.4-rc3 (648b1dd)`. This commit includes:
  - `958e1ade` "accurip: parse CDDB ID with strtoul" (fixes #145, the AccurateRip bug);
  - `e843c0b4` "src/naming: keep the drive letter of an absolute Windows path" (closes #109, the `-D` bug);
  - `7dbe56aa` "check for media changes at most once a second" (#165). The rip loop used to ask the drive about media changes before every frame, which halved rip speed on a PIONEER drive. This box has a PIONEER BDR-S11JX.

  The commits after `7dbe56aa` only change upstream's CI, so `648b1ddd` is the newest source, and its `static-build.sh` gives the dependency versions we mirror.
- The build script is `tools/cyanrip/build.ps1` (entry point) plus `build.sh`. It runs in a user-space MSYS2 (MINGW64, like upstream's own Windows builds). Docker and WSL aren't usable on this box, and nothing is installed system-wide. Everything is pinned:
  - the MSYS2 snapshot (sha256 in `build.ps1`);
  - the toolchain: every package beyond the snapshot, with its sha256, in `msys2-packages.lock`;
  - every library: tarball URL and sha256 in `versions.sh`, or a git commit;
  - cyanrip itself: the commit, fetched by hash.

  Libraries are linked statically, and the script refuses an exe that needs any non-Windows DLL. Left out on purpose: libqrencode (QR codes on stdout) and chromaprint (AcoustID). AMA does its own MusicBrainz work and wants neither.
- The zip (`cyanrip.exe`, `LICENSE.md`, `BUILDINFO.txt`) is published to the Forgejo generic package registry of `mintopia` (owner of `mintopia/automatic-media-archive`) as package `cyanrip`, version `0.9.4-rc3-g648b1dd`. `src/ama/tools.py` pins that URL, the zip's SHA-256 and `cyanrip.exe`'s SHA-256. Package versions are never overwritten: a new build is a new version.

## Consequences
- AccurateRip works for every Disc, so Review only sees real mismatches and Discs missing from the database. We checked this on CUE images with the exact TOCs of two captured Discs. For CDDB ID `DC10A212` (cyanrip issue #93), 0.9.3.1 says `AccurateRip: not found` and this build says `found`. For the FFVII Rebirth disc 1 (`57129218`), both say `found`, with the same Disc ID. AMA's `parse_report` / `tracks_from_info` read this build's `-I` output exactly as they read the 0.9.3 capture. A Rip of a synthetic image with AMA's `rip_command` passes `rip_succeeded`.
- We now carry an unreleased upstream (an RC) whose CLI and output changed since 0.9.3.1: `-v` replaces `-V`, data tracks are ripped to `.bin` unless `-X` is given, and the CUE gives a hidden track as track 1 `INDEX 00`. AMA's parser must keep up with this build, not with the 0.9.3.1 docs.
- Upstream runs its tests only on Linux and macOS. On Windows the build runs the three unit suites that work there and every disc-image rip scenario. The FUN512 unit test needs POSIX `mkstemp`, and the `verify_log` scenario covers the same ground.
- The inputs are pinned, but the exe isn't bit-for-bit reproducible across build folders: build paths end up in the binary. The published hashes are of the published build.
- A clean rebuild needs about 3 GB under `%LOCALAPPDATA%\ama-build\cyanrip` and roughly an hour on this box. Configure scripts are slow under MSYS2, so the larger libraries use CMake/Ninja. Old MSYS2 package versions can disappear from repo.msys2.org; if a locked file is gone, run `build.ps1 -Relock` and commit the new lock.
- When upstream tags a release that contains these fixes, we can go back to pinning its official asset and supersede this ADR.

### Rebuilding and publishing a new version
1. Change `CYANRIP_COMMIT` and `CYANRIP_VERSION` (and any dependency pins) in `tools/cyanrip/versions.sh`. `PACKAGE_VERSION` follows from them.
2. `.\tools\cyanrip\build.ps1 -Fresh -InfoDevice D:`. This sets up MSYS2 again from the snapshot and the lock, then rebuilds every library and cyanrip from source. It runs the tests, checks the exe's DLLs and its `-v`, then runs `cyanrip -I` on the CD in D: (it never rips). Check the `AccurateRip:` line, and prefer a Disc whose `CDDB ID` starts with 8 to F.
3. `.\tools\cyanrip\build.ps1 -PublishOnly` uploads the zip to `https://git.mintopia.net/api/packages/mintopia/generic/cyanrip/<version>/<file>` with the key from `~\.forgejo`. It prints the zip's sha256. Downloads need no token: the `mintopia` owner is public.
4. Update the cyanrip `Pin` in `src/ama/tools.py`: version, url, the zip's sha256, and `cyanrip.exe`'s sha256 (both printed by the build). Update the package table in `docs/deploy.md` too. Then run the tests.

## Supersedes
None. This refines ADR 0006's cyanrip pin, and ADR 0006 still holds.
