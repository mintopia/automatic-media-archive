"""The Encode's picture: progressive output and auto-crop.

Pure functions only; `moviearchive.py` runs the analysis and hands the result to
`encode.ffmpeg_args` as one `-vf` chain (notes/research/ffmpeg.md §5-6):

- Before the Encode, ffmpeg looks at `SAMPLES` short stretches spread over the
  Main Feature (skipping the first and last 5%: logos, credits) with
  `idet,cropdetect` (`sample_args`).
- Scan type (DVDs only): film that was hard-telecined to 29.97 repeats a field in
  about 2 of every 5 frames, so idet's repeated-field count gives it away; it is
  detelecined back to film rate (fieldmatch + decimate, bwdif mops up the odd
  frame left combed). Combed frames with a steady field order and no repeats are
  true interlaced video: bwdif, one frame per field (59.94/50p), keeping its
  motion. Anything else is progressive already (soft-telecined DVDs are: the
  pulldown is only flags, so their frames keep film timing) and gets no filter.
- Crop: the union of every sample's box. A dark scene only ever makes a box
  smaller, so one bright sample is enough to keep the picture whole; boxes from
  all-black samples are thrown away. An axis is only cropped when at least two
  samples reach each of its edges (bars line up, scene content doesn't), the bars
  total `MIN_BAR` px or more, and at least `MIN_KEEP` of it stays. Cropping
  happens after detelecine/deinterlace.

The thresholds come from synthetic sources (tests/data/ffmpeg); calibrate on
real Discs if one is misjudged.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

SAMPLES = 10
SAMPLE_FRAMES = 240
MIN_BAR = 8  # px removed per axis before a crop is worth it
EDGE_AGREE = 2  # samples that must reach each edge of the crop
EDGE_SLACK = 4  # px
# Share of each axis a crop must keep. Real bars leave more (a 2.39:1 film
# letterboxed in a 4:3 DVD keeps 56% of its height); less is a dark scene's content.
MIN_KEEP = 0.5
REPEATED_TELECINE = 0.15  # share of frames with a repeated field (3:2 pulldown ~0.4)
COMBED_INTERLACED = 0.25  # share of decided frames idet calls TFF/BFF
STEADY_ORDER = 0.8  # one field order's share of those combed frames
CROPDETECT = "cropdetect=limit=0.1:round=2:reset_count=0"  # fractional limit: any bit depth


class Scan(StrEnum):
    PROGRESSIVE = "progressive"
    TELECINED = "telecined"
    INTERLACED = "interlaced"


@dataclass(frozen=True)
class Crop:
    w: int
    h: int
    x: int
    y: int

    @property
    def filter(self) -> str:
        return f"crop={self.w}:{self.h}:{self.x}:{self.y}"


@dataclass(frozen=True)
class Fields:
    """idet's totals (multi-frame detection, and repeated fields)."""

    tff: int = 0
    bff: int = 0
    progressive: int = 0
    undetermined: int = 0
    neither: int = 0
    top: int = 0
    bottom: int = 0

    def __add__(self, other: Fields) -> Fields:
        return Fields(*(a + b for a, b in zip(self._values(), other._values(), strict=True)))

    def _values(self) -> tuple[int, ...]:
        return (self.tff, self.bff, self.progressive, self.undetermined, self.neither,
                self.top, self.bottom)


@dataclass(frozen=True)
class Sample:
    fields: Fields
    box: Crop | None  # None: cropdetect found nothing but black (or didn't run)


@dataclass(frozen=True)
class ScanResult:
    scan: Scan
    order: str = "tff"  # "tff" | "bff"


@dataclass(frozen=True)
class Picture:
    """What the Encode does to the picture."""

    scan: ScanResult
    crop: Crop | None
    width: int
    height: int

    @property
    def filters(self) -> str | None:
        """The `-vf` chain, or None when the picture goes through untouched."""
        chain = []
        if self.scan.scan == Scan.TELECINED:
            chain += [f"fieldmatch=order={self.scan.order}:combmatch=full",
                      "bwdif=mode=send_frame:parity=auto:deint=interlaced", "decimate"]
        elif self.scan.scan == Scan.INTERLACED:
            chain += ["bwdif=mode=send_field:parity=auto:deint=all"]
        if self.crop is not None:
            chain.append(self.crop.filter)
        return ",".join(chain) or None

    def describe(self) -> str:
        """For the Disc log."""
        scan = {Scan.PROGRESSIVE: "progressive",
                Scan.TELECINED: f"telecined film ({self.scan.order.upper()}), "
                                "detelecined to film rate",
                Scan.INTERLACED: f"interlaced ({self.scan.order.upper()}), deinterlaced "
                                 "to one frame per field"}[self.scan.scan]
        crop = (f"cropped {self.width}x{self.height} to {self.crop.w}x{self.crop.h} "
                f"at {self.crop.x},{self.crop.y}" if self.crop else "no black bars to crop")
        return f"Picture: {scan}; {crop}"


_IDET = re.compile(r"(Repeated Fields|Multi frame detection):\s*(.*)")
_COUNT = re.compile(r"(\w+):\s*(\d+)")
_CROP = re.compile(r"crop=(-?\d+):(-?\d+):(-?\d+):(-?\d+)")


def parse_sample(lines: Iterable[str]) -> Sample:
    """One `sample_args` run's output: idet's last summary, cropdetect's last box."""
    repeated: dict[str, int] = {}
    multi: dict[str, int] = {}
    box: Crop | None = None
    for line in lines:
        if "cropdetect" in line and (m := _CROP.search(line)):
            w, h, x, y = map(int, m.groups())
            box = Crop(w, h, x, y) if w > 0 and h > 0 else None
        elif "idet" in line and (m := _IDET.search(line)):
            counts = {k.lower(): int(v) for k, v in _COUNT.findall(m.group(2))}
            if sum(counts.values()):  # ffmpeg also prints an empty summary per graph
                (repeated if m.group(1) == "Repeated Fields" else multi).update(counts)
    return Sample(Fields(multi.get("tff", 0), multi.get("bff", 0), multi.get("progressive", 0),
                         multi.get("undetermined", 0), repeated.get("neither", 0),
                         repeated.get("top", 0), repeated.get("bottom", 0)), box)


def _edges(lo: list[int], hi: list[int], size: int) -> tuple[int, int]:
    """One axis of the union box: bars sit still, so an edge counts only if EDGE_AGREE samples
    reach it and the bar is at least MIN_BAR."""
    start, end = min(lo), max(hi)
    agreed = (sum(abs(v - start) <= EDGE_SLACK for v in lo) >= EDGE_AGREE
              and sum(abs(v - end) <= EDGE_SLACK for v in hi) >= EDGE_AGREE)
    if not agreed or start + (size - end) < MIN_BAR or end - start < size * MIN_KEEP:
        return 0, size
    start -= start % 2
    end = min(size, end + end % 2)
    return start, end


def crop_for(samples: Sequence[Sample], width: int, height: int) -> Crop | None:
    """The crop that removes the black bars every sample agrees on, or None."""
    boxes = [s.box for s in samples if s.box is not None]
    if len(boxes) < EDGE_AGREE or not width or not height:
        return None
    x0, x1 = _edges([b.x for b in boxes], [b.x + b.w for b in boxes], width)
    y0, y1 = _edges([b.y for b in boxes], [b.y + b.h for b in boxes], height)
    crop = Crop(x1 - x0, y1 - y0, x0, y0)
    return None if (crop.w, crop.h) == (width, height) else crop


def scan_type(samples: Sequence[Sample], fps: float) -> ScanResult:
    f = sum((s.fields for s in samples), Fields())
    combed = f.tff + f.bff
    order = "bff" if f.bff > f.tff else "tff"
    decided = combed + f.progressive
    if not decided or combed / decided < COMBED_INTERLACED \
            or max(f.tff, f.bff) / combed < STEADY_ORDER:
        return ScanResult(Scan.PROGRESSIVE)
    fields = f.neither + f.top + f.bottom
    film = fields and (f.top + f.bottom) / fields >= REPEATED_TELECINE
    ntsc = abs(fps - 30000 / 1001) < 0.05
    return ScanResult(Scan.TELECINED if film and ntsc else Scan.INTERLACED, order)


def sample_times(duration_s: float) -> list[float]:
    """Where the samples start: evenly over the middle 90% of the feature."""
    if duration_s <= 0:
        return [0.0]
    start, span = duration_s * 0.05, duration_s * 0.9
    return [round(start + span * (i + 0.5) / SAMPLES, 3) for i in range(SAMPLES)]


def sample_args(exe: Path, src: Path, at_s: float, *, idet: bool) -> list[str]:
    """One analysis run: `SAMPLE_FRAMES` frames from `at_s`, to the null muxer."""
    vf = f"idet,{CROPDETECT}" if idet else CROPDETECT
    return [str(exe), "-hide_banner", "-nostdin", "-nostats", "-hwaccel", "cuda",
            "-ss", f"{at_s:.3f}", "-i", str(src), "-map", "0:v:0",
            "-frames:v", str(SAMPLE_FRAMES), "-vf", vf, "-an", "-sn", "-f", "null", "-"]


def analyse(runs: Iterable[Iterable[str]], *, width: int, height: int, fps: float,
            detect_scan: bool) -> Picture:
    """The Picture for the Encode, from the output of each `sample_args` run."""
    found = [parse_sample(lines) for lines in runs]
    scan = scan_type(found, fps) if detect_scan else ScanResult(Scan.PROGRESSIVE)
    return Picture(scan, crop_for(found, width, height), width, height)
