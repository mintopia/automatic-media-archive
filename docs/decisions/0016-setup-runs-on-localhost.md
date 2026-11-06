# Decision: With no settings file, AMA runs Setup in the browser, on localhost only

Status: accepted
Date: 2026-11-06

## Context
A missing `ama.toml` used to be a hard error telling the user to copy the example file. That is a poor first run for a tray app with no visible console. The web UI binds to `0.0.0.0` with no password by default, so a first-run screen there would let anyone on the LAN choose the folders AMA writes to.

## Decision
- **No settings file means Setup.** AMA starts and serves only the Setup pages until Setup finishes. There is no `setup_complete` flag: an existing file means Setup is done. Settings remains the only place to change values afterwards, and Setup cannot be re-run.
- **Setup binds to `127.0.0.1`**, whatever the eventual host will be. The tray's "Open AMA" opens it locally.
- Setup asks only what is needed to start, in this order: Welcome (the tool downloads begin) → drive and MakeMKV status (doesn't block) → Library paths (Scratch under "Advanced") → TMDB key (skippable; a skipped key leaves a persistent, dismissable warning) → "Reach AMA from other devices?" (default yes, which sets `0.0.0.0`) with an optional password → Ready.
- Everything else, including `[encode.cq]`, gets built-in defaults. Setup writes the file with the `SettingsFile` writer (ADR 0008), then AMA moves to the chosen host.

## Consequences
- A fresh install never shows an error, and no one else on the LAN can take over the Setup window.
- Configuring a headless machine needs a local browser, or a hand-written `ama.toml`, which skips Setup.
- **The Linux container (ADR 0009, later) must differ:** there, remote access is the default, and Setup must be reachable from outside the container. The Linux work needs its own guard for that, for example a one-time Setup token printed to the container log.

## Supersedes
None. This refines ADR 0008: the file is still the only settings source.
