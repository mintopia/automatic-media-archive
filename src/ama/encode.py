"""The Encode of a Main Feature: stream selection, the ffmpeg command, its progress.

Pure functions only; `moviearchive.py` runs them. Policy (ticket #6, ADR-0002):
- video: the first real video stream, hevc_nvenc Main10 (p010) at the Disc Type's CQ;
- audio, passed through untouched: every English track (commentaries too), plus the
  film's original-language track when the film isn't English. A Disc with neither
  keeps its first audio track, so the Encode is never silent;
- subtitles, copied: every English track, plus forced tracks with no language tag;
- chapters and global tags are kept.
Default tracks: the original-language audio; an English film shows only its forced
subtitles, a foreign film its full English subtitles.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ama.config import CqConfig
from ama.drive import DiscType
from ama.hdr import Colour, colour_args

ENGLISH = frozenset({"eng", "en"})

# ISO 639-1 (TMDB `original_language`) -> the ISO 639-2 codes a Disc may tag it with
# (bibliographic and terminology forms both occur).
_ISO_639_2: dict[str, tuple[str, ...]] = {
    "en": ("eng",), "fr": ("fre", "fra"), "de": ("ger", "deu"), "es": ("spa",),
    "it": ("ita",), "ja": ("jpn",), "ko": ("kor",), "zh": ("chi", "zho"), "cn": ("chi", "zho"),
    "ru": ("rus",), "pt": ("por",), "nl": ("dut", "nld"), "sv": ("swe",), "da": ("dan",),
    "no": ("nor", "nob", "nno"), "nb": ("nob", "nor"), "fi": ("fin",), "is": ("ice", "isl"),
    "pl": ("pol",), "cs": ("cze", "ces"), "sk": ("slo", "slk"), "hu": ("hun",),
    "ro": ("rum", "ron"), "el": ("gre", "ell"), "tr": ("tur",), "he": ("heb",),
    "ar": ("ara",), "fa": ("per", "fas"), "hi": ("hin",), "ta": ("tam",), "te": ("tel",),
    "bn": ("ben",), "th": ("tha",), "vi": ("vie",), "id": ("ind",), "ms": ("may", "msa"),
    "tl": ("tgl", "fil"), "uk": ("ukr",), "sr": ("srp",), "hr": ("hrv",), "bg": ("bul",),
    "ca": ("cat",), "eu": ("baq", "eus"), "gl": ("glg",), "ga": ("gle",), "cy": ("wel", "cym"),
    "et": ("est",), "lv": ("lav",), "lt": ("lit",), "sl": ("slv",), "ka": ("geo", "kat"),
    "hy": ("arm", "hye"), "ur": ("urd",), "pa": ("pan",), "ml": ("mal",), "kn": ("kan",),
    "mr": ("mar",), "yue": ("chi", "zho", "yue"),
}


def language_codes(iso_639_1: str) -> frozenset[str]:
    """Every tag a stream in this (TMDB) language may carry."""
    code = iso_639_1.lower()
    return frozenset({code, *_ISO_639_2.get(code, ())}) if code else frozenset()


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
    def height(self) -> int:
        video = next((s for s in self.streams if s.kind == "video" and not s.attached_pic), None)
        return video.height if video else 0


def parse_probe(text: str) -> Probe:
    """ffprobe `-show_streams -show_chapters -show_format -of json` output.

    Raises ValueError if there is no JSON object in `text`.
    """
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
            attached_pic=bool(d.get("attached_pic")), height=int(s.get("height") or 0)))
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

    @property
    def streams(self) -> tuple[Stream, ...]:
        return (self.video, *self.audio, *self.subtitles)


class NoVideo(ValueError):
    pass


def select_streams(probe: Probe, original_language: str) -> Selection:
    """Apply the track policy (module docstring). `original_language` is ISO 639-1."""
    video = next((s for s in probe.streams if s.kind == "video" and not s.attached_pic), None)
    if video is None:
        raise NoVideo("the Main Feature has no video stream")
    audio_all = [s for s in probe.streams if s.kind == "audio"]
    original_codes = language_codes(original_language)
    original_is_english = bool(original_codes & ENGLISH)
    original = next((s for s in audio_all if s.language in original_codes and not s.commentary),
                    None)
    keep = [s for s in audio_all if s.english or s is original]
    if not keep and audio_all:
        keep = [audio_all[0]]
    default_audio = original or next((s for s in keep if not s.commentary), keep[0] if keep else None)
    if default_audio is None:
        raise NoVideo("the Main Feature has no audio")
    subs = [s for s in probe.streams if s.kind == "subtitle"
            and (s.english or (s.is_forced and not s.language))]
    forced = next((s for s in subs if s.is_forced), None)
    full = None
    if not original_is_english and default_audio is original:
        full = next((s for s in subs if not s.is_forced and not s.sdh), None) or \
            next((s for s in subs if not s.is_forced), None)
    return Selection(video, tuple(keep), tuple(subs), default_audio, original, forced, full)


def cq_for(cq: CqConfig, disc_type: DiscType) -> int:
    return {DiscType.DVD: cq.dvd, DiscType.BD: cq.bd, DiscType.UHD: cq.uhd}[disc_type]


# hevc_nvenc settings (notes/research/ffmpeg.md §1); CQ is per Disc Type, from config.
VIDEO_OPTS = ["-c:v", "hevc_nvenc", "-preset", "p7", "-tune", "hq", "-rc", "vbr",
              "-b:v", "0", "-profile:v", "main10", "-pix_fmt", "p010le",
              "-rc-lookahead", "32", "-spatial-aq", "1", "-bf", "4",
              "-temporal-aq", "1", "-b_ref_mode", "middle"]  # verified on this GPU (#11)


def _flags(*named: tuple[str, bool]) -> str:
    return "+".join(name for name, on in named if on) or "0"


def ffmpeg_args(exe: Path, src: Path, dest: Path, sel: Selection, cq: int,
                title: str, colour: Colour | None = None) -> list[str]:
    """`colour`: tag the video with it (HDR10 sources; `hdr.py` checks the result)."""
    args = [str(exe), "-hide_banner", "-nostdin", "-nostats", "-loglevel", "warning",
            "-progress", "pipe:1", "-y", "-hwaccel", "cuda", "-i", str(src)]
    for s in sel.streams:
        args += ["-map", f"0:{s.index}"]
    args += ["-map_chapters", "0", "-map_metadata", "0", "-metadata", f"title={title}",
             *VIDEO_OPTS[:8], "-cq", str(cq), *VIDEO_OPTS[8:],
             *(colour_args(colour) if colour else []),
             "-c:a", "copy", "-c:s", "copy"]
    for i, a in enumerate(sel.audio):
        args += [f"-disposition:a:{i}", _flags(("default", a is sel.default_audio),
                                               ("original", a is sel.original_audio),
                                               ("comment", a.commentary),
                                               ("hearing_impaired", a.hearing_impaired))]
    for i, s in enumerate(sel.subtitles):
        is_default = s is sel.default_subtitle or (s is sel.forced_subtitle
                                                   and sel.default_subtitle is None)
        args += [f"-disposition:s:{i}", _flags(("default", is_default),
                                               ("forced", s.is_forced),
                                               ("hearing_impaired", s.sdh))]
    return args + ["-max_muxing_queue_size", "4096", "-default_mode", "passthrough",
                   "-f", "matroska", str(dest)]


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
    """Feed it ffmpeg's output lines; `-progress` blocks come back as EncodeProgress.

    Lines that aren't progress keys (warnings on stderr) return None.
    """

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
