# Decision: UHD Encodes keep HDR10 only; Dolby Vision and HDR10+ dropped

Status: accepted
Date: 2026-11-04

## Context
NVENC cannot encode Dolby Vision or carry HDR10+ dynamic metadata. Preserving
DV means extracting the RPU, converting profile 7 to 8.1 with dovi_tool and
re-injecting it with exact frame-count alignment (crop requires RPU edits).
Because the Encode is the permanent Archive (ADR-0002), this choice cannot be
revisited without re-ripping.

## Decision
UHD Encodes are HEVC Main10 with HDR10 static metadata (colour tags, mastering
display, MaxCLL/MaxFALL) preserved and verified. DV RPU and HDR10+ SEI are
discarded.

## Consequences
- DV-capable displays fall back to HDR10.
- Adding DV later is a new pipeline stage plus re-ripping already archived UHDs.

## Supersedes
None
