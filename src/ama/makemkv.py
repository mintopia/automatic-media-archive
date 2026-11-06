"""makemkvcon in robot mode (`-r`): command lines and output parsing.

Robot output is one record per line, `PREFIX:` then comma-separated fields with
quoted, backslash-escaped strings. We key off MSG *codes* and attribute ids,
never the (localised) text, except as a fallback for licence errors.
Reference: https://www.makemkv.com/developers/usage.txt and apdefs.h.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from pathlib import Path

from ama.drive import DiscType

PROGRESS_MAX = 65536  # AP_Progress_MaxValue

# MSG codes
MSG_SAVING = 5014  # "Saving %1 titles into directory %2": the copy itself starts
MSG_COPY_COMPLETE = 5037  # "Copy complete. %1 titles saved, %2 failed."
MSG_TITLE_TOO_SHORT = 3025
MSG_TITLE_DUPLICATE = 3309  # code unverified; the text check below is the fallback
LICENCE_ALWAYS = {5021, 5055}  # version too old / evaluation over, shareware gone
LICENCE_EXCEPT_DVD = {5052}  # evaluation over; free DVD ripping still works
AP_UIMSG_BOXERROR = 516

# TINFO / SINFO attribute ids (AP_ItemAttributeId)
A_TYPE, A_NAME, A_DURATION, A_SIZE_BYTES = 1, 2, 9, 11
A_SOURCE, A_SEGMENTS_COUNT, A_SEGMENTS_MAP, A_OUTPUT_FILE = 16, 25, 26, 27
TYPE_AUDIO, TYPE_SUBTITLES = 6202, 6203


@dataclass(frozen=True)
class Msg:
    code: int
    flags: int
    text: str
    params: tuple[str, ...]

    @property
    def is_error(self) -> bool:
        return self.flags & 0xFFFF == AP_UIMSG_BOXERROR


@dataclass(frozen=True)
class Progress:
    current: int
    total: int
    max: int

    @property
    def fraction(self) -> float:
        return min(1.0, self.total / self.max) if self.max else 0.0


@dataclass(frozen=True)
class Drv:
    index: int
    state: int
    flags: int
    name: str
    disc_name: str
    device: str

    @property
    def has_disc(self) -> bool:
        return self.state == 2  # AP_DriveStateInserted

    @property
    def exists(self) -> bool:
        return self.state != 256 and bool(self.name)  # 256 = AP_DriveStateNoDrive


@dataclass(frozen=True)
class CInfo:
    attr: int
    code: int
    value: str


@dataclass(frozen=True)
class TInfo:
    title: int
    attr: int
    code: int
    value: str


@dataclass(frozen=True)
class SInfo:
    title: int
    stream: int
    attr: int
    code: int
    value: str


RobotLine = Msg | Progress | Drv | CInfo | TInfo | SInfo | None


def split_fields(s: str) -> list[str]:
    out: list[str] = []
    buf: list[str] = []
    quoted = escaped = False
    for ch in s:
        if escaped:
            buf.append(ch)
            escaped = False
        elif quoted and ch == "\\":
            escaped = True
        elif ch == '"':
            quoted = not quoted
        elif ch == "," and not quoted:
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    out.append("".join(buf))
    return out


def parse_line(line: str) -> RobotLine:
    """One robot line, or None for lines we don't use (or can't parse)."""
    prefix, sep, rest = line.strip().partition(":")
    if not sep:
        return None
    f = split_fields(rest)
    try:
        match prefix:
            case "MSG" if len(f) >= 5:
                count = int(f[2])
                return Msg(int(f[0]), int(f[1]), f[3], tuple(f[5:5 + count]))
            case "PRGV" if len(f) >= 3:
                return Progress(int(f[0]), int(f[1]), int(f[2]))
            case "DRV" if len(f) >= 6:
                return Drv(int(f[0]), int(f[1]), int(f[3]), f[4], f[5], f[6] if len(f) > 6 else "")
            case "CINFO" if len(f) >= 3:
                return CInfo(int(f[0]), int(f[1]), f[2])
            case "TINFO" if len(f) >= 4:
                return TInfo(int(f[0]), int(f[1]), int(f[2]), f[3])
            case "SINFO" if len(f) >= 5:
                return SInfo(int(f[0]), int(f[1]), int(f[2]), int(f[3]), f[4])
    except ValueError:
        return None
    return None


def licence_problem(msg: Msg, disc_type: DiscType) -> bool:
    """True when MakeMKV refuses to work until its key (or version) is fixed."""
    if msg.code in LICENCE_ALWAYS:
        return True
    if msg.code in LICENCE_EXCEPT_DVD:
        return disc_type != DiscType.DVD
    if msg.code == 5075:  # "new version available": shown on every run, harmless
        return False
    t = msg.text.lower()
    return "registration key" in t or "evaluation period" in t or "too old" in t


def libredrive_refused(messages: Iterable[Msg]) -> bool:
    """Whether MakeMKV couldn't open a UHD for want of LibreDrive mode (by text: the MSG code is
    unknown)."""
    return any("libredrive" in (t := m.text.lower()) and "required" in t for m in messages)


def parse_duration(s: str) -> int:
    seconds = 0
    for part in s.split(":"):
        seconds = seconds * 60 + int(part or 0)
    return seconds


@dataclass(frozen=True)
class TitleInfo:
    id: int
    name: str = ""
    duration_s: int = 0
    size_bytes: int = 0
    source: str = ""
    segments_count: int = 0
    segments_map: str = ""
    output_file: str = ""
    audio: int = 0
    subtitles: int = 0


@dataclass
class Scan:
    drives: list[Drv] = field(default_factory=list)
    titles: list[TitleInfo] = field(default_factory=list)
    messages: list[Msg] = field(default_factory=list)
    skipped_short: int = 0  # dropped by MakeMKV's --minlength
    skipped_duplicates: int = 0  # dropped by MakeMKV as equal to another title
    disc_name: str = ""  # CINFO 2: MakeMKV's name for the Disc
    volume_name: str = ""  # CINFO 32


def parse_scan(lines: Iterable[str]) -> Scan:
    """The result of `makemkvcon -r info ...`."""
    return parse_scan_records(map(parse_line, lines))


def parse_scan_records(records: Iterable[RobotLine]) -> Scan:
    scan = Scan()
    titles: dict[int, TitleInfo] = {}
    for rec in records:
        match rec:
            case Drv():
                scan.drives.append(rec)
            case Msg():
                scan.messages.append(rec)
                if rec.code == MSG_TITLE_TOO_SHORT:
                    scan.skipped_short += 1
                elif rec.code == MSG_TITLE_DUPLICATE or "is equal to title" in rec.text:
                    scan.skipped_duplicates += 1
            case CInfo(attr=2, value=v):
                scan.disc_name = v
            case CInfo(attr=32, value=v):
                scan.volume_name = v
            case TInfo(title=t, attr=a, value=v):
                info = titles.setdefault(t, TitleInfo(id=t))
                try:
                    match a:
                        case 2: info = replace(info, name=v)
                        case 9: info = replace(info, duration_s=parse_duration(v))
                        case 11: info = replace(info, size_bytes=int(v))
                        case 16: info = replace(info, source=v)
                        case 25: info = replace(info, segments_count=int(v))
                        case 26: info = replace(info, segments_map=v)
                        case 27: info = replace(info, output_file=v)
                except ValueError:
                    pass
                titles[t] = info
            case SInfo(title=t, attr=1, code=code, value=v):
                info = titles.setdefault(t, TitleInfo(id=t))
                if code == TYPE_AUDIO or (not code and v == "Audio"):
                    titles[t] = replace(info, audio=info.audio + 1)
                elif code == TYPE_SUBTITLES or (not code and v == "Subtitles"):
                    titles[t] = replace(info, subtitles=info.subtitles + 1)
    scan.titles = [titles[t] for t in sorted(titles)]
    return scan


@dataclass(frozen=True)
class Selection:
    keep: list[TitleInfo]
    short: list[TitleInfo]
    duplicates: list[tuple[TitleInfo, TitleInfo]]  # (dropped, the kept Title it repeats)


def select_titles(titles: Iterable[TitleInfo], min_seconds: int) -> Selection:
    """Titles worth ripping: long enough, and not the exact same segments (and length) as an
    earlier one. A DVD numbers its cells afresh in each title set, so two different episodes
    can share a segment map; only the length tells them apart."""
    keep: list[TitleInfo] = []
    short: list[TitleInfo] = []
    dupes: list[tuple[TitleInfo, TitleInfo]] = []
    seen: dict[tuple[str, int, int], TitleInfo] = {}
    for t in sorted(titles, key=lambda t: t.id):
        if t.duration_s < min_seconds:
            short.append(t)
            continue
        key = (t.segments_map, t.segments_count, t.duration_s)
        if t.segments_map and key in seen:
            dupes.append((t, seen[key]))
            continue
        if t.segments_map:
            seen[key] = t
        keep.append(t)
    return Selection(keep, short, dupes)


def rip_summary(records: Iterable[RobotLine]) -> tuple[int, int] | None:
    """(saved, failed) from the "Copy complete" line of an `mkv` run, if it got that far."""
    result = None
    for r in records:
        if isinstance(r, Msg) and r.code == MSG_COPY_COMPLETE and len(r.params) >= 2:
            try:
                result = (int(r.params[0]), int(r.params[1]))
            except ValueError:
                pass
    return result


# Command lines. The same scan options must go to `info` and `mkv <id>`, or the
# Title ids won't line up.

def _scan_opts(min_seconds: int) -> list[str]:
    return ["-r", "--progress=-same", "--noscan", f"--minlength={min_seconds}"]


def drives_args(exe: Path) -> list[str]:
    """List drives only (cheap). Also the cheapest licence check: it runs first."""
    return [str(exe), "-r", "--cache=1", "info", "disc:9999"]


def info_args(exe: Path, source: str, min_seconds: int) -> list[str]:
    return [str(exe), *_scan_opts(min_seconds), "info", source]


def mkv_args(exe: Path, source: str, title_id: int, dest: Path, min_seconds: int) -> list[str]:
    return [str(exe), *_scan_opts(min_seconds), "mkv", source, str(title_id), str(dest)]


def pick_source(drives: Iterable[Drv]) -> str | None:
    """`disc:N` for the drive holding the Disc (this box has one drive)."""
    drives = list(drives)
    for d in drives:
        if d.has_disc:
            return f"disc:{d.index}"
    for d in drives:
        if d.exists:
            return f"disc:{d.index}"
    return None
