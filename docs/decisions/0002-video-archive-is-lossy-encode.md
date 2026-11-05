# Decision: Video Archive is a lossy Encode; no lossless master kept

Status: accepted (encoder wording superseded by 0010)
Date: 2026-11-04

## Context
Video Discs could be archived as a full disc backup, a lossless MKV remux, a
lossy Encode, or a remux master plus Encode. A UHD remux is ~50-100 GB; storage
cost for lossless masters across the collection is prohibitive.

## Decision
The Archive for DVD/BD/UHD is the NVENC HEVC Encode only (RTX 3060 Ti: no AV1
encode). The lossless Rip is a temporary intermediate, deleted after a
successful Encode. CDs remain lossless (FLAC).

## Consequences
- Encode settings are effectively permanent: changing quality means re-ripping the Disc.
- Encode quality/HDR handling deserves care up front.
- Physical Disc is the only lossless source.

## Supersedes
None
