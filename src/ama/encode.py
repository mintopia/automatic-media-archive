"""The Encode of a Main Feature: stream selection, the ffmpeg command, its progress.

Pure functions only; `encoder.py` runs them. Policy (ADR-0002, configurable per ADR
0010; the defaults, shown here, are v1's):
- video: the first real video stream, 10-bit, at the Disc Type's constant quality, with
  the configured encoder (`ENCODERS`, default hevc_nvenc) and speed step; optionally
  scaled down to a maximum resolution;
- audio (`TrackPolicy.audio`), passed through untouched: "languages" keeps every track
  in a preferred language (commentaries too, default English), plus the film's
  original-language track. "all" keeps every track; "first_plus_stereo" the first
  track plus an AAC stereo copy of it. A Disc with none of them keeps its first
  audio track, so the Encode is never silent;
- subtitles (`TrackPolicy.subtitles`), copied: "languages" keeps every track in a
  preferred language, plus forced tracks with no language tag; or "all", or "none";
- chapters and global tags are kept.
Default tracks: the original-language audio; a film in a preferred language shows only
its forced subtitles, any other film the full subtitles of the most preferred
language that has them.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import get_args

from ama.config import AudioChoice, CqConfig, EncodeConfig, EncoderName, Speed, SubtitleChoice
from ama.drive import DiscType
from ama.hdr import HdrInfo, colour_args
from ama.languages import language_codes

ENGLISH = frozenset({"eng", "en"})


@dataclass(frozen=True)
class Stream:
    index: int
    kind: str  # "video" | "audio" | "subtitle" | ...
    codec: str
    language: str = ""  # lower-case tag; "" = untagged / "und"
    title: str = ""
    default: bool = False
    forced: bool = False
    comment: bool = False
    hearing_impaired: bool = False
    attached_pic: bool = False
    height: int = 0
    width: int = 0
    frame_rate: float = 0.0  # 0 = unknown

    @property
    def english(self) -> bool:
        return self.language in ENGLISH

    @property
    def commentary(self) -> bool:
        return self.comment or "commentary" in self.title.lower()

    @property
    def is_forced(self) -> bool:
        return self.forced or "forced" in self.title.lower()

    @property
    def sdh(self) -> bool:
        t = self.title.lower()
        return self.hearing_impaired or "sdh" in t.split() or "hearing" in t


@dataclass(frozen=True)
class Probe:
    streams: tuple[Stream, ...]
    duration_s: float
    chapters: int = 0

    @property
    def video(self) -> Stream | None:
        return next((s for s in self.streams if s.kind == "video" and not s.attached_pic), None)

    @property
    def height(self) -> int:
        return self.video.height if self.video else 0


def _rate(text: object) -> float:
    """ffprobe's `r_frame_rate` ("30000/1001"); 0.0 when absent or "0/0"."""
    num, _, den = str(text or "").partition("/")
    try:
        return float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        return 0.0


def parse_probe(text: str) -> Probe:
    """ffprobe's JSON (streams, chapters, format); ValueError if there is none."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("ffprobe printed no JSON")
    data = json.loads(text[start:end + 1])
    streams = []
    for s in data.get("streams", []):
        tags = {k.lower(): v for k, v in (s.get("tags") or {}).items()}
        d = s.get("disposition") or {}
        lang = str(tags.get("language", "")).lower()
        streams.append(Stream(
            index=int(s["index"]), kind=s.get("codec_type", ""), codec=s.get("codec_name", ""),
            language="" if lang == "und" else lang, title=str(tags.get("title", "")),
            default=bool(d.get("default")), forced=bool(d.get("forced")),
            comment=bool(d.get("comment")), hearing_impaired=bool(d.get("hearing_impaired")),
            attached_pic=bool(d.get("attached_pic")), height=int(s.get("height") or 0),
            width=int(s.get("width") or 0), frame_rate=_rate(s.get("r_frame_rate"))))
    try:
        duration = float((data.get("format") or {}).get("duration") or 0)
    except ValueError:
        duration = 0.0
    return Probe(tuple(streams), duration, len(data.get("chapters") or []))


@dataclass(frozen=True)
class Selection:
    """The streams the Encode keeps, in output order, and which are flagged."""

    video: Stream
    audio: tuple[Stream, ...]
    subtitles: tuple[Stream, ...]
    default_audio: Stream
    original_audio: Stream | None
    forced_subtitle: Stream | None
    default_subtitle: Stream | None
    stereo: Stream | None = None  # the audio track also written as AAC stereo, after `audio`

    @property
    def streams(self) -> tuple[Stream, ...]:
        """Every output stream's source, in output order (`stereo` maps its track again)."""
        return (self.video, *self.audio, *((self.stereo,) if self.stereo else ()),
                *self.subtitles)


@dataclass(frozen=True)
class TrackPolicy:
    """Which sound and subtitle tracks an Encode keeps (ADR 0010); defaults are v1's."""

    audio: AudioChoice = "languages"
    subtitles: SubtitleChoice = "languages"
    languages: tuple[str, ...] = ("en",)  # ISO 639-1, most preferred first

    @classmethod
    def of(cls, cfg: EncodeConfig) -> TrackPolicy:
        return cls(cfg.audio, cfg.subtitles, cfg.preferred_languages)


class NoVideo(ValueError):
    pass


def _first(streams: list[Stream], *tests: Callable[[Stream], bool]) -> Stream | None:
    return next((s for s in streams if all(t(s) for t in tests)), None)


def select_streams(probe: Probe, original_language: str,
                   policy: TrackPolicy = TrackPolicy()) -> Selection:
    """Apply the track policy (module docstring). `original_language` is ISO 639-1."""
    video = next((s for s in probe.streams if s.kind == "video" and not s.attached_pic), None)
    if video is None:
        raise NoVideo("the Main Feature has no video stream")
    audio_all = [s for s in probe.streams if s.kind == "audio"]
    original_codes = language_codes(original_language)
    preferred = [language_codes(code) for code in policy.languages]
    wanted = frozenset().union(*preferred)
    original = _first(audio_all, lambda s: s.language in original_codes,
                      lambda s: not s.commentary)
    match policy.audio:
        case "all":
            keep = audio_all
        case "first_plus_stereo":
            keep = audio_all[:1]
        case "languages":
            keep = [s for s in audio_all if s.language in wanted or s is original]
    if not keep and audio_all:
        keep = [audio_all[0]]
    if not keep:
        raise NoVideo("the Main Feature has no audio")
    if not any(s is original for s in keep):
        original = None
    stereo = keep[0] if policy.audio == "first_plus_stereo" else None
    default_audio = stereo or original or _first(keep, lambda s: not s.commentary) or keep[0]
    subs_all = [s for s in probe.streams if s.kind == "subtitle"]
    match policy.subtitles:
        case "all":
            subs = subs_all
        case "none":
            subs = []
        case "languages":
            subs = [s for s in subs_all
                    if s.language in wanted or (s.is_forced and not s.language)]
    forced = _first(subs, lambda s: s.is_forced)
    full = None
    if original is not None and default_audio is original and not original_codes & wanted:
        for codes in preferred:  # the most preferred language with full subtitles
            full_subs = [s for s in subs if s.language in codes and not s.is_forced]
            full = _first(full_subs, lambda s: not s.sdh) or _first(full_subs)
            if full:
                break
    return Selection(video, tuple(keep), tuple(subs), default_audio, original, forced, full,
                     stereo)


def cq_for(cq: CqConfig, disc_type: DiscType) -> int:
    return {DiscType.DVD: cq.dvd, DiscType.BD: cq.bd, DiscType.UHD: cq.uhd}[disc_type]


@dataclass(frozen=True)
class EncoderProfile:
    """One encoder's ffmpeg video options (ADR 0010) and how Settings names it."""

    label: str
    note: str  # under the label in Settings, when it works
    quality: str  # its constant-quality option, given the Disc Type's CQ
    presets: tuple[str, str, str, str]  # by speed step, fastest first (`SPEEDS`)
    before: tuple[str, ...]  # options between -preset and the quality
    after: tuple[str, ...]  # options after the quality
    hwaccel: tuple[str, ...] = ()  # decode options, before -i
    slowest: tuple[str, ...] = ()  # added for the slowest step


SPEEDS: tuple[Speed, ...] = get_args(Speed)  # fastest first
SPEED_LABELS: dict[Speed, str] = {"faster": "Faster, bigger", "balanced": "Balanced",
                                  "slower": "Slower, smaller", "slowest": "Slowest, smallest"}

# hevc_nvenc is v1's (notes/research/ffmpeg.md §1), verified on the RTX 3060 Ti; its
# "slower" step (the default) is v1's p7, and "slowest" adds a full-resolution second
# pass. The preset per step is calibrated in #17.
_NVENC_RC = ("-tune", "hq", "-rc", "vbr")
ENCODERS: dict[EncoderName, EncoderProfile] = {
    "hevc_nvenc": EncoderProfile(
        "HEVC (NVIDIA)", "Fast; the default", "-cq", ("p4", "p6", "p7", "p7"), _NVENC_RC,
        ("-b:v", "0", "-profile:v", "main10", "-pix_fmt", "p010le", "-rc-lookahead", "32",
         "-spatial-aq", "1", "-bf", "4", "-temporal-aq", "1", "-b_ref_mode", "middle"),
        hwaccel=("-hwaccel", "cuda"), slowest=("-multipass", "fullres")),
    "av1_nvenc": EncoderProfile(
        "AV1 (NVIDIA)", "Smaller files; older Plex apps may have to convert them", "-cq",
        ("p4", "p6", "p7", "p7"), _NVENC_RC,
        ("-b:v", "0", "-pix_fmt", "p010le", "-rc-lookahead", "32", "-spatial-aq", "1",
         "-temporal-aq", "1"),
        hwaccel=("-hwaccel", "cuda"), slowest=("-multipass", "fullres")),
    "hevc_qsv": EncoderProfile(
        "HEVC (Intel Quick Sync)", "Fast on Intel graphics", "-global_quality",
        ("faster", "medium", "slower", "veryslow"), (),
        ("-profile:v", "main10", "-pix_fmt", "p010le")),
    "libx265": EncoderProfile(
        "HEVC (software)", "Works on any PC; very slow for UHD", "-crf",
        ("fast", "medium", "slow", "slower"), (),
        ("-profile:v", "main10", "-pix_fmt", "yuv420p10le")),
}


def _x265_params(hdr: HdrInfo | None) -> list[str]:
    """libx265 writes HDR10's mastering display and light levels only when told."""
    params = ["log-level=error"]  # x265 logs to stderr whatever ffmpeg's -loglevel
    if hdr is not None:
        params += ["hdr10=1", "repeat-headers=1"]
        if hdr.mastering is not None:
            rx, ry, gx, gy, bx, by, wx, wy, lo, hi = hdr.mastering.key()
            params.append(f"master-display=G({gx},{gy})B({bx},{by})R({rx},{ry})"
                          f"WP({wx},{wy})L({hi},{lo})")
        if hdr.max_cll is not None:
            params.append(f"max-cll={hdr.max_cll},{hdr.max_fall or 0}")
    return ["-x265-params", ":".join(params)]


def video_args(encoder: EncoderName, speed: Speed, cq: int,
               hdr: HdrInfo | None = None) -> list[str]:
    """The video encoder's options. `hdr` (an HDR10 source) tags the output with its
    colour (ADR-0003); `hdr.py` checks the finished Encode kept all of it."""
    p = ENCODERS[encoder]
    return ["-c:v", encoder, "-preset", p.presets[SPEEDS.index(speed)], *p.before,
            p.quality, str(cq), *p.after, *(p.slowest if speed == "slowest" else ()),
            *(_x265_params(hdr) if encoder == "libx265" else ()),
            *(colour_args(hdr.colour) if hdr else ())]


# The largest picture each maximum resolution allows (a cropped film keeps its shape).
_MAX_BOX = {"1080p": (1920, 1080), "720p": (1280, 720)}


def scale_filter(max_resolution: str) -> str | None:
    """The `scale` filter for a `[encode.max_resolution]` value; None for "keep"."""
    if max_resolution not in _MAX_BOX:
        return None
    w, h = _MAX_BOX[max_resolution]
    return (f"scale=w='min(iw,{w})':h='min(ih,{h})':force_original_aspect_ratio=decrease"
            ":force_divisible_by=2")


STEREO_BITRATE = "192k"


def _flags(*named: tuple[str, bool]) -> str:
    return "+".join(name for name, on in named if on) or "0"


def ffmpeg_args(exe: Path, src: Path, dest: Path, sel: Selection, cq: int,
                title: str, video_filter: str | None = None, *, hdr: HdrInfo | None = None,
                encoder: EncoderName = "hevc_nvenc", speed: Speed = "slower",
                max_resolution: str = "keep") -> list[str]:
    """`hdr`: an HDR10 source's metadata, kept (`video_args`). `video_filter`: the `-vf`
    chain from `picture.Picture.filters`, if any; `max_resolution` scales after it."""
    args = [str(exe), "-hide_banner", "-nostdin", "-nostats", "-loglevel", "warning",
            "-progress", "pipe:1", "-y", *ENCODERS[encoder].hwaccel, "-i", str(src)]
    for s in sel.streams:
        args += ["-map", f"0:{s.index}"]
    chain = ",".join(f for f in (video_filter, scale_filter(max_resolution)) if f)
    if chain:
        args += ["-vf", chain]
    args += ["-map_chapters", "0", "-map_metadata", "0", "-metadata", f"title={title}",
             *video_args(encoder, speed, cq, hdr), "-c:a", "copy"]
    stereo = len(sel.audio)  # the stereo copy's output audio index
    if sel.stereo:
        args += [f"-c:a:{stereo}", "aac", f"-ac:a:{stereo}", "2", f"-b:a:{stereo}",
                 STEREO_BITRATE, f"-metadata:s:a:{stereo}", "title=Stereo"]
    if sel.subtitles:
        args += ["-c:s", "copy"]
    for i, a in enumerate(sel.audio):
        args += [f"-disposition:a:{i}", _flags(("default", a is sel.default_audio),
                                               ("original", a is sel.original_audio),
                                               ("comment", a.commentary),
                                               ("hearing_impaired", a.hearing_impaired))]
    if sel.stereo:
        args += [f"-disposition:a:{stereo}", "0"]
    for i, s in enumerate(sel.subtitles):
        is_default = s is sel.default_subtitle or (s is sel.forced_subtitle
                                                   and sel.default_subtitle is None)
        args += [f"-disposition:s:{i}", _flags(("default", is_default),
                                               ("forced", s.is_forced),
                                               ("hearing_impaired", s.sdh))]
    return args + ["-max_muxing_queue_size", "4096", "-default_mode", "passthrough",
                   "-f", "matroska", str(dest)]


# The test encode (ADR 0010): 5 s of a 1080p test pattern through the real video options.
PROBE_PATTERN = "testsrc2=size=1920x1080:rate=24:duration=5"
PROBE_CQ = 22


def probe_args(exe: Path, encoder: EncoderName, speed: Speed) -> list[str]:
    """A test encode with `encoder`: exit 0 means it works on this PC."""
    return [str(exe), "-hide_banner", "-nostdin", "-nostats", "-loglevel", "error",
            "-f", "lavfi", "-i", PROBE_PATTERN, *video_args(encoder, speed, PROBE_CQ),
            "-f", "null", "-"]


def ffprobe_args(exe: Path, src: Path) -> list[str]:
    return [str(exe), "-v", "error", "-show_streams", "-show_chapters", "-show_format",
            "-of", "json", str(src)]


@dataclass(frozen=True)
class EncodeProgress:
    fraction: float
    speed: float | None = None  # x realtime
    eta_s: int | None = None

    @property
    def pct(self) -> int:
        return int(self.fraction * 100)


class ProgressReader:
    """Turns ffmpeg's `-progress` lines into EncodeProgress (None for other lines)."""

    KEYS = frozenset({"frame", "fps", "bitrate", "total_size", "out_time_us", "out_time_ms",
                      "out_time", "dup_frames", "drop_frames", "speed", "progress"})

    def __init__(self, duration_s: float) -> None:
        self._duration = duration_s
        self._block: dict[str, str] = {}

    def is_progress(self, line: str) -> bool:
        key, sep, _ = line.strip().partition("=")
        return bool(sep) and (key in self.KEYS or key.startswith("stream_"))

    def feed(self, line: str) -> EncodeProgress | None:
        if not self.is_progress(line):
            return None
        key, _, value = line.strip().partition("=")
        self._block[key] = value.strip()
        if key != "progress":
            return None
        block, self._block = self._block, {}
        if value.strip() == "end":
            return EncodeProgress(1.0)
        try:
            t = int(block.get("out_time_us", "")) / 1e6
        except ValueError:
            t = 0.0
        try:
            speed: float | None = float(block.get("speed", "").rstrip("x").strip())
        except ValueError:
            speed = None
        fraction = min(1.0, max(0.0, t / self._duration)) if self._duration > 0 else 0.0
        eta = int((self._duration - t) / speed) if speed and self._duration > t else None
        return EncodeProgress(fraction, speed, eta)
