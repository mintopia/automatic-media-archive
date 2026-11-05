# Decision: Rip first, identify later; Review gates only Encode and filing

Status: accepted
Date: 2026-11-04

## Context
With one drive, drive time is the throughput bottleneck. Identification can be
low-confidence and need a human, and for video Discs the Titles worth keeping
(Main Feature, Episodes, Extras) can depend on Identification.

## Decision
Every inserted Disc is Ripped immediately (all Titles at or above the
configured minimum length for its Disc Type, default 30 s; duplicates dropped)
and ejected, regardless of Identification confidence. Identification
runs alongside; low-confidence results go to Review. Encode and filing to the
Archive wait on accepted Identification. Scratch is deleted after filing.

## Consequences
- Needs local scratch (>= 256 GB); when full, new Discs are refused rather than ripped.
- Ripped-but-unreviewed Discs accumulate on scratch if Review lags.
- Title selection happens after the Rip, from scratch (thumbnails in Review), without reinserting the Disc.

## Supersedes
None

Amended 2026-11-05: the 30 s minimum Title length is now a per-Disc-Type
setting (default 30 s), recorded on each Job. Exception: while a Rip runs, the
user may untick Titles that haven't started; they are Skipped and never ripped.
Ripping takes long enough that dropping an unwanted Title early is worth it.
