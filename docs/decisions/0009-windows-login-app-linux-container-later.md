# Decision: Windows login app with a supervisor now; Linux container later

Status: accepted
Date: 2026-11-04

## Context
AMA needs to restart itself (settings that only apply at startup) and start
unattended. A Windows service runs in session 0 under an account without the
user's MakeMKV registration, NAS credentials or easy drive access. AMA should
eventually also ship for Linux as a container with the drive (and optionally a
GPU for hardware Encode) passed through.

## Decision
On Windows AMA is a per-user app started at login: `ama run` is a small
supervisor with a tray icon (Open UI, Pause, Restart, Quit) that relaunches the
server. The server restarts itself only by exiting with a dedicated restart
exit code; the supervisor (Windows) or the container restart policy (Linux)
brings it back. The Linux container is not built yet, but new code avoids
Windows-only assumptions: the drive may be a device path, the NAS may be a
mounted path, and the tray is Windows-only.

## Consequences
- No Windows service; AMA runs only while the user is logged in.
- One restart path for both platforms.
- Platform-specific code stays behind small seams (drive, NAS, tray).

## Supersedes
None
