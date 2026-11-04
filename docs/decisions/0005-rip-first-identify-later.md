# Decision: Rip first, identify later; Review gates only Encode and filing

Status: accepted
Date: 2026-11-04

## Context
With one drive, drive time is the throughput bottleneck. Identification can be
low-confidence and need a human, and for video Discs the Titles worth keeping
(Main Feature, Episodes, Extras) can depend on Identification.

## Decision
Every inserted Disc is Ripped immediately (all Titles >= 30 s, duplicates
dropped) and ejected, regardless of Identification confidence. Identification
runs alongside; low-confidence results go to Review. Encode and filing to the
Archive wait on accepted Identification. Scratch is deleted after filing.

## Consequences
- Needs local scratch (>= 256 GB); when full, new Discs are refused rather than ripped.
- Ripped-but-unreviewed Discs accumulate on scratch if Review lags.
- Title selection happens after the Rip, from scratch (thumbnails in Review), without reinserting the Disc.

## Supersedes
None
