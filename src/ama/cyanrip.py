"""cyanrip: the command lines AMA runs, and parsing what cyanrip prints.

cyanrip (ADR-0004) prints the same report to stdout and to its `.log`: a header,
a `Gaps:` block, one block per track, then a footer. Progress meters go to
stdout only, redrawn with `\\r`. Formats are from cyanrip 0.9.3.1
(src/cyanrip_log.c, src/cyanrip_main.c); see notes in tests/data/cyanrip/.

`parse_report` reads both the info-only run (`-I`, "Track N info:" blocks) and
a real Rip ("Track N ripped and encoded successfully!" blocks), so one parser
gives the TOC before the Rip and the per-track results after it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

SAMPLE_RATE = 44100
FRAMES_PER_SECOND = 75  # CD frames (sectors) per second


class ArStatus(StrEnum):
    """AccurateRip verdict for one track."""

    ACCURATE = "accurate"        # v1 or v2 checksum matched the database
    MISMATCH = "mismatch"        # the Disc is in the database but this track didn't match
    NOT_IN_DB = "not_in_db"      # the Disc isn't in the database (new or rare pressing)
    UNAVAILABLE = "unavailable"  # lookup failed or was disabled: no verdict


@dataclass(frozen=True)
class ArResult:
    status: ArStatus
    confidence: int | None = None  # set for ACCURATE: number of matching submissions


@dataclass(frozen=True)
class Progress:
    track: int
    percent: float          # of this track
    eta_seconds: int | None  # for the whole Disc
    errors: int


@dataclass
class TrackReport:
    number: int
    is_data: bool = False
    seconds: float = 0.0
    preemphasis: bool = False
    ripped: bool = False      # "Track N ripped and encoded successfully!"
    ar: ArResult | None = None  # None in info-only output (no checksums yet)


@dataclass
class Report:
    disc_tracks: int | None = None
    disc_id: str | None = None
    mcn: str | None = None           # "Disc MCN:" (the barcode, when the CD carries one)
    device_model: str | None = None
    accuraterip: str | None = None   # header: found | not found | error | mismatch | disabled
    htoa_frames: int | None = None   # hidden track before track 1, split off as track 0
    tracks: dict[int, TrackReport] = field(default_factory=dict)
    ripping_errors: int | None = None  # footer; None if cyanrip never got there
    offset_unset: bool = False

    @property
    def audio_tracks(self) -> list[TrackReport]:
        return [t for n, t in sorted(self.tracks.items()) if not t.is_data]


_PROGRESS = re.compile(
    r"^Ripping (?:and encoding )?track (\d+), progress - ([\d.]+)%"
    r"(?:, ETA - (?:(\d+)h )?(?:(\d+)m)?(?:(\d+)s)?)?(?:, errors - (\d+))?\s*$"
)


def parse_progress(line: str) -> Progress | None:
    m = _PROGRESS.match(line.strip())
    if not m:
        return None
    track, pct, h, mi, s, errs = m.groups()
    eta = None
    if h or mi or s:
        eta = int(h or 0) * 3600 + int(mi or 0) * 60 + int(s or 0)
    return Progress(int(track), float(pct), eta, int(errs or 0))


_TRACK_START = re.compile(
    r"^Track (\d+) (?:info:|is data:|ripped and encoded successfully!)\s*$"
)
_HEADER = {
    "Disc tracks:": "disc_tracks",
    "DiscID:": "disc_id",
    "Disc MCN:": "mcn",
    "Device model:": "device_model",
    "AccurateRip:": "accuraterip",
}
_HTOA = re.compile(r"^(\d+) frame pregap in track 1, splitting off into a new track, number 0")
_AR_LINE = re.compile(r"^Accurip v[12]:\s+[0-9A-F]{8} \(accurately ripped, confidence (\d+)\)")


def parse_report(text: str) -> Report:
    """Parse cyanrip's report (stdout, `-I` output, or the `.log`)."""
    r = Report()
    track: TrackReport | None = None
    for raw in re.split(r"[\r\n]", text):
        line = raw.strip()
        if not line or parse_progress(line):
            continue
        if m := _TRACK_START.match(line):
            n = int(m.group(1))
            track = r.tracks.setdefault(n, TrackReport(n))
            if "is data" in line:
                track.is_data = True
            elif "successfully" in line:
                track.ripped = True
            continue
        if line.startswith("Offset is unset!"):
            r.offset_unset = True
        elif m := _HTOA.match(line):
            r.htoa_frames = int(m.group(1))
        elif line.startswith("Ripping errors:"):
            r.ripping_errors = int(line.split(":", 1)[1])
            track = None
        elif line.startswith(("Tracks ripped accurately:", "Paranoia status counts:")):
            track = None
        elif track is None:
            for key, attr in _HEADER.items():
                if line.startswith(key) and getattr(r, attr) is None:
                    value = line[len(key):].strip()
                    setattr(r, attr, int(value) if attr == "disc_tracks" else value)
        else:
            _track_line(r, track, line)
    return r


def _track_line(r: Report, t: TrackReport, line: str) -> None:
    if line.startswith("Preemphasis:"):
        t.preemphasis = line.split(":", 1)[1].strip().startswith("present")
    elif line.startswith("Data bytes:"):
        t.is_data = True
    elif line.startswith("Samples:"):
        t.seconds = int(line.split(":", 1)[1]) / SAMPLE_RATE
    elif line.startswith("Accurip:"):
        v = line.split(":", 1)[1].strip()
        if v.startswith("disc found in database"):
            t.ar = ArResult(ArStatus.MISMATCH)  # upgraded by a matching v1/v2 line below
        elif v.startswith("not found"):
            status = ArStatus.UNAVAILABLE if r.accuraterip in ("error", "disabled") \
                else ArStatus.NOT_IN_DB
            t.ar = ArResult(status)
        else:
            t.ar = ArResult(ArStatus.UNAVAILABLE)
    elif m := _AR_LINE.match(line):
        conf = int(m.group(1))
        best = t.ar.confidence if t.ar and t.ar.confidence else 0
        t.ar = ArResult(ArStatus.ACCURATE, max(conf, best))


def rip_succeeded(report: Report, returncode: int, expected_tracks: int) -> bool:
    """cyanrip exits 0 for some non-rips, so also require a clean footer and every track."""
    return (
        returncode == 0
        and report.ripping_errors == 0
        and not report.offset_unset
        and sum(t.ripped for t in report.audio_tracks) >= expected_tracks
    )


# ---- command lines ---------------------------------------------------------

def _common(device: str, offset: int) -> list[str]:
    return [
        "-d", device,
        "-s", str(offset),
        "-p", "1=track",  # a hidden track before track 1 is kept as track 0
        "-W",             # never de-emphasise: pre-emphasis is flagged in the cue instead
        "-N", "-U", "-G",  # no MusicBrainz / cover art from cyanrip; Identification does that
    ]


def info_command(exe: str | Path, device: str, offset: int) -> list[str]:
    """Read the TOC (tracks, lengths, pre-emphasis, hidden track, data tracks); no Rip."""
    return [str(exe), *_common(device, offset), "-I"]


def rip_command(exe: str | Path, device: str, offset: int, out_dir: str, retries: int) -> list[str]:
    """Secure Rip to per-track FLAC + cue + log in `out_dir` (relative to the cwd).

    cyanrip 0.9.3.1 mangles absolute Windows paths in -D (issue #109), so run it
    with cwd = the scratch folder and a relative `out_dir`.
    """
    return [
        str(exe), *_common(device, offset),
        "-P", "3", "-r", str(retries), "-o", "flac",
        "-D", out_dir, "-F", "{track}", "-L", "rip", "-M", "rip",
    ]
