# Decision: The Windows installer is a uv bootstrap, and installed data lives in %LOCALAPPDATA%\AMA

Status: accepted
Date: 2026-11-06

## Context
Public users need an installer, not a git clone. A frozen app (PyInstaller plus Inno Setup) works offline. Its drawbacks: it is large, prone to antivirus false positives, and would redistribute every dependency, including LGPL pystray, which ADR 0012 avoids. AMA can't work offline anyway: it downloads ffmpeg and cyanrip (ADR 0006) and calls TMDB and MusicBrainz.

## Decision
- **The installer `AMA-Setup-x.y.z.exe` is built with Inno Setup and carries `uv.exe` and AMA's wheel.** At install time, uv installs a pinned Python and AMA's locked dependencies into the app folder.
- **Per-user install with no admin rights.** The installer:
  - adds a Start-menu entry;
  - adds "Start AMA when I sign in", on by default (ADR 0009);
  - launches AMA when done, which opens Setup (ADR 0016).
- **Settings, database and logs default to `%LOCALAPPDATA%\AMA\`.** `--config` and `AMA_CONFIG` still override that, and Scratch keeps its own setting. The existing development install moves its files there once.
- **Uninstall** removes the app. It keeps `%LOCALAPPDATA%\AMA\` (and never touches Libraries) unless the user ticks "also remove settings and history".
- **Updates notify, they don't self-update.** AMA checks GitHub Releases for a newer `vX.Y.Z` and shows "Update available" with a link. Running the new installer upgrades in place.
- **Unsigned for now.** The Install page explains the SmartScreen warning. Code signing is to be looked into separately.
- The release workflow (ADR 0013) builds the installer on a Windows runner from the `vX.Y.Z` tag and attaches it to the GitHub Release.

## Consequences
- The installer is small, and only AMA's own MIT code and uv are redistributed.
- Installing needs network access, which AMA's first run needs anyway.
- Unsigned installers put off some users until signing is in place.

## Supersedes
None
