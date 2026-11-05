# Decision: AMA doesn't manage storage; Libraries are plain paths

Status: accepted
Date: 2026-11-05

## Context
v1 connected to a NAS itself (`[nas]` UNC path and credentials, `net use`,
a reconnect loop, NAS Runs in Logs) and required every Library to sit inside
the NAS root. Mounting storage is the user's concern: a Library folder may be a
local disk, a mapped drive, a UNC path or (on Linux) a mount, and AMA can't
manage all of those well.

## Decision
AMA no longer connects to or mounts anything. There is no Archive root: each
Library has its own folder path, wherever it lives. If a Library folder isn't
reachable when a Job is filed, the Job waits at "Encoded · filing" and filing is
retried every minute, with a Problem saying which folder isn't reachable. An
existing `ama.toml` is rewritten once at startup: each Library's path is resolved
against the old `nas.unc`, `[nas]` is dropped and a `.bak` is kept. The Plex
path mapping stays as an optional "Plex sees Libraries at" prefix.

## Consequences
- No storage credentials are kept; one less secret to mask.
- A disconnected drive or share is reported, never fixed, by AMA.
- Old NAS Runs stay readable in Logs; no new ones are recorded.
- Removes the NAS seam named in ADR 0009.

## Supersedes
The NAS parts of ADR 0009 (the NAS credentials in its Context and the NAS seam
in its Decision and Consequences).
