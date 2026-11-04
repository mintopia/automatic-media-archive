# Decision: AMA provisions portable ffmpeg and cyanrip; MakeMKV is the user's

Status: accepted
Date: 2026-11-04

## Context
AMA drives three external tools: MakeMKV (`makemkvcon`) for video Rips, cyanrip for CD Rips (ADR 0004), and ffmpeg/ffprobe for Encodes. Relying on whatever happens to be on the box gave us missing tools and untested versions. MakeMKV differs from the other two: it is licensed per user, needs a key or the beta key, and its builds expire ("This application version is too old").

## Decision
- **ffmpeg/ffprobe and cyanrip are AMA's job.** AMA downloads its own portable copies into a per-user tools directory, outside the repo. Each tool's version and SHA-256 are pinned in code. Provisioning is idempotent: skip when the pinned version is present and the hash matches, re-download when it's missing or corrupt, and never touch a system-wide install. A config setting can override a tool's path. Bumping a version means changing the pin.
- **MakeMKV is the user's job.** AMA never installs, updates or registers it. AMA checks for it: is `makemkvcon` present, does it run (a too-old build reports MSG 5021), and is it registered. If any check fails, AMA shows the user what's wrong and how to fix it: where to download it, how to enter a key or the beta key. Video Rips are refused until the checks pass.

## Consequences
- Rips and Encodes run against known tool versions, so the parsers can rely on the output formats.
- The first start needs internet access and a few hundred MB of disk.
- Upgrading ffmpeg or cyanrip is a code change.
- If ffmpeg's NVENC build needs a newer NVIDIA driver than the box has, that shows up as a failed Encode on the box itself, not in CI.

## Supersedes
None
