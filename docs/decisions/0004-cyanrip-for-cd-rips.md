# Decision: cyanrip for CD Rips; AccurateRip only, no CTDB

Status: accepted
Date: 2026-11-04

## Context
CD Rips must run headless on Windows with secure ripping and verification.
EAC and CUERipper are GUI-only; dBpoweramp's CLI is paid; whipper is Linux-only.
cyanrip runs on Windows (MinGW builds) with AccurateRip v1/v2, cue, log,
MusicBrainz tagging and cover art, but no CTDB.

## Decision
Use cyanrip. A track failing AccurateRip, or a Disc absent from the AccurateRip
database, goes to Review rather than being filed silently.

## Consequences
- No CTDB second opinion or repair; rarer pressings will often need Review.
- cyanrip's secure-read quality on the Windows drive backend is unproven; verify on the target drive during the pilot.
- Revisit if CUETools can be scripted for CTDB verify.

## Supersedes
None
