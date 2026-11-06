# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Python (uv) app on a Windows box; server-rendered FastAPI + Jinja + htmx with live updates via SSE. No SPA, no JS build step.

## Users

The owner (technical) and household members. Household members feed Discs into the drive and may do Review, so the UI must be understandable without knowing the tooling (AccurateRip, CQ, TMDB, MakeMKV). Used on a phone standing at the drive while feeding Discs, and on desktop for longer Review sessions.

## Product Purpose

Semi-automated archiving of the household's own physical media (CD, DVD, Blu-ray, UHD Blu-ray) into Plex Libraries, wherever their folders live (a local disk, a mapped drive or a network share; mounting storage is the user's concern, ADR 0011). A person inserts a Disc; the system Rips, Identifies, Encodes and archives it. Humans only step in when Identification is low-confidence or something fails. Success: Discs flow through with minimal attention, and nothing lands in the Archive mis-named.

## Operating Context

- One optical drive; drive time is the bottleneck. A Disc is ripped and ejected immediately; Identification, Review and Encode happen afterwards from local scratch.
- The UI is the place to see what the drive and pipeline are doing right now, and the queue of Discs awaiting Review.
- Notifications (Discord, ntfy, a Webhook) pull people back to the UI when Review is needed, a Disc is done ("insert next"), or a Disc failed.
- LAN only; optional shared password.

## Capabilities and Constraints

- Domain vocabulary per `GLOSSARY.md`: Disc, Disc Type, Title, Main Feature, Extra, Episode, Rip, Encode, Identification, Review, Archive.
- Review covers: picking a MusicBrainz release or manual album entry (CD); picking a TMDB match and Main Feature with Title thumbnails (movies); mapping Titles to Episodes (TV); categorising Extras (optional); multi-disc sets.
- Failures: Disc ejected and marked failed with a viewable log; no auto-retry.
- Repeat Discs warn before ripping; full scratch refuses new Discs.
- Decisions in `docs/decisions/0002`–`0005` are binding.

## Evidence on Hand

No real screenshots, cover art or library data yet; mockups use placeholder titles. Do not fabricate brand assets.

## Product Principles

1. Glanceable from across the room: drive state and "what do I do next" are obvious in one look.
2. Plain language first; technical detail (logs, verification results) available but secondary.
3. Never let a wrong match into the Archive silently: uncertainty is shown, not hidden.
4. The human's job is small and specific; every Review asks one clear question.

## Accessibility & Inclusion

WCAG 2.2 AA. Follows system light/dark theme; both must be complete. Touch targets sized for phone use.
