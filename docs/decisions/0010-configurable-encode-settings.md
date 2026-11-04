# Decision: Encode settings are configurable

Status: accepted
Date: 2026-11-04

## Context
ADR 0002 fixed the video Archive as an NVENC HEVC Encode. Users on other
hardware (or a future Linux container) need other encoders, and a few choices
(audio, subtitles, languages, resolution) are a matter of taste.

## Decision
The Archive is still a lossy Encode with no lossless master (ADR 0002 stands on
that). The encoder is configurable: `hevc_nvenc`, `av1_nvenc`, `hevc_qsv` or
`libx265`, offered only when a test encode proves it works on this machine.
Also configurable: CQ/CRF and maximum resolution per Disc Type, preset, audio
(copy all / first plus AAC stereo / by language), subtitles (all / by language
/ none) and preferred languages. The container stays MKV and quality stays
constant-quality; no plain bitrate setting. A Job's Encode settings are fixed
when its Encode Phase starts.

## Consequences
- Archives made at different times may use different encoders or settings.
- AMA must probe encoders at startup and on save and warn when one stops working.
- `libx265` is available but very slow for UHD.

## Supersedes
ADR 0002's "NVENC HEVC only" wording (its lossy-Archive decision stands).
