"""HDR10 static metadata of a video stream, and checking an Encode kept it (ADR-0003).

Pure functions; `moviearchive.py` runs ffprobe. HDR10 = PQ transfer (smpte2084)
with its colour tags, mastering display (SMPTE ST 2086) and content light
levels (MaxCLL/MaxFALL). hevc_nvenc carries the mastering display and light
levels over from the decoded frames by itself (FFmpeg 7.1+); AMA sets the colour
tags explicitly and checks all of it on the finished Encode. Dolby Vision and
HDR10+ are dropped by the re-encode, which is what ADR-0003 wants.

The first frame's side data (the HEVC SEI) is preferred, the stream's (MKV Colour
elements) is the fallback. Values are fractions whose denominators differ between
the two (34000/50000 vs 17/25), so they are compared as values, rounded to the
SEI's units (chromaticity 1/50000, luminance 1/10000).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

PQ = "smpte2084"
_MASTERING = "Mastering display metadata"
_LIGHT = "Content light level metadata"
_DOVI = ("DOVI configuration record", "Dolby Vision RPU Data", "Dolby Vision Metadata")
_HDR10_PLUS = "HDR Dynamic Metadata SMPTE2094-40 (HDR10+)"

Point = tuple[Fraction, Fraction]


@dataclass(frozen=True)
class Colour:
    primaries: str = ""
    transfer: str = ""
    space: str = ""
    range: str = ""


@dataclass(frozen=True)
class MasteringDisplay:
    red: Point
    green: Point
    blue: Point
    white: Point
    min_luminance: Fraction
    max_luminance: Fraction

    def key(self) -> tuple[int, ...]:
        """In SEI units, so equal values compare equal whatever their denominators."""
        xy = [round(v * 50000) for p in (self.red, self.green, self.blue, self.white) for v in p]
        return (*xy, round(self.min_luminance * 10000), round(self.max_luminance * 10000))

    def __str__(self) -> str:
        return (f"{float(self.min_luminance):g}-{float(self.max_luminance):g} nits, "
                f"white point {float(self.white[0]):.4f},{float(self.white[1]):.4f}")


@dataclass(frozen=True)
class HdrInfo:
    colour: Colour
    mastering: MasteringDisplay | None = None
    max_cll: int | None = None
    max_fall: int | None = None
    dolby_vision: bool = False
    hdr10_plus: bool = False

    @property
    def is_hdr10(self) -> bool:
        return self.colour.transfer == PQ

    def __str__(self) -> str:
        light = (f"MaxCLL {self.max_cll}, MaxFALL {self.max_fall}" if self.max_cll is not None
                 else "no light levels")
        return f"{self.mastering or 'no mastering display'}; {light}"


def probe_args(exe: Path, src: Path) -> list[str]:
    """ffprobe for the first video frame and its stream, with their side data."""
    return [str(exe), "-v", "error", "-select_streams", "v:0", "-read_intervals", "%+#1",
            "-show_streams", "-show_frames", "-of", "json", str(src)]


def _tag(value: object) -> str:
    v = str(value or "")
    return "" if v in ("unknown", "unspecified", "reserved") else v


def _frac(value: object) -> Fraction:
    return Fraction(str(value))


def parse_hdr(text: str) -> HdrInfo:
    """`probe_args` output. Raises ValueError if it isn't ffprobe JSON."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("ffprobe printed no JSON")
    data = json.loads(text[start:end + 1])
    frame = (data.get("frames") or [{}])[0]
    stream = (data.get("streams") or [{}])[0]

    def pick(key: str) -> str:
        return _tag(frame.get(key)) or _tag(stream.get(key))

    colour = Colour(pick("color_primaries"), pick("color_transfer"), pick("color_space"),
                    pick("color_range"))
    side: dict[str, dict] = {}
    for d in [*(stream.get("side_data_list") or []), *(frame.get("side_data_list") or [])]:
        side[d.get("side_data_type", "")] = d  # the frame's copy wins
    mastering = None
    if (m := side.get(_MASTERING)) and "red_x" in m:
        p = {c: (_frac(m[f"{c}_x"]), _frac(m[f"{c}_y"]))
             for c in ("red", "green", "blue", "white_point")}
        mastering = MasteringDisplay(p["red"], p["green"], p["blue"], p["white_point"],
                                     _frac(m["min_luminance"]), _frac(m["max_luminance"]))
    light = side.get(_LIGHT) or {}
    return HdrInfo(colour, mastering,
                   int(light["max_content"]) if "max_content" in light else None,
                   int(light["max_average"]) if "max_average" in light else None,
                   dolby_vision=any(k in side for k in _DOVI),
                   hdr10_plus=_HDR10_PLUS in side)


def differences(source: HdrInfo, encode: HdrInfo) -> list[str]:
    """What the Encode lost or changed of the source's HDR10 metadata; [] = it matches."""
    out = []
    for field in ("primaries", "transfer", "space", "range"):
        want, got = getattr(source.colour, field), getattr(encode.colour, field)
        if want and got != want:
            out.append(f"{field} is {got or 'untagged'}, not {want}")
    if source.mastering is not None:
        if encode.mastering is None:
            out.append("the mastering display metadata is missing")
        elif encode.mastering.key() != source.mastering.key():
            out.append(f"the mastering display is {encode.mastering}, not {source.mastering}")
    for name, want, got in (("MaxCLL", source.max_cll, encode.max_cll),
                            ("MaxFALL", source.max_fall, encode.max_fall)):
        if want is not None and got != want:
            out.append(f"{name} is {got if got is not None else 'missing'}, not {want}")
    if encode.dolby_vision:
        out.append("Dolby Vision metadata is still there")
    if encode.hdr10_plus:
        out.append("HDR10+ metadata is still there")
    return out


def colour_args(colour: Colour) -> list[str]:
    """Tag the Encode with the source's colour description (untagged fields left out)."""
    args = []
    for opt, value in (("-color_primaries", colour.primaries), ("-color_trc", colour.transfer),
                       ("-colorspace", colour.space), ("-color_range", colour.range)):
        if value:
            args += [opt, value]
    return args
