"""Naming Patterns: the rule a Library files names by (GLOSSARY).

A pattern is literal text and `{field}` placeholders; `/` separates folders, `{{` and
`}}` are literal braces, and `{track:02}` zero-pads (nothing else from Python's format
syntax). It is relative to the Library's folder and has no extension. A field with no
value drops out with the text around it: `{title} ({year})` with no year is `Title`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath

from ama.archive import safe_chars, safe_name

SEGMENT_LIMIT = 240  # a whole folder or file name, under NTFS's 255 with room for an extension


class Kind(StrEnum):
    """What a pattern names: each kind has its own fields and default."""

    FILM = "film"
    TV = "tv"
    MUSIC_SINGLE_DISC = "music_single_disc"
    MUSIC_MULTI_DISC = "music_multi_disc"


Value = str | int | None


@dataclass(frozen=True)
class Field:
    """A placeholder a pattern can use, as the editor lists it."""

    name: str
    example: Value
    about: str


_FILM = (
    Field("title", "Ocean's Eleven", "The film's title on TMDB"),
    Field("year", 2001, "Its release year"),
    Field("tmdb_id", 161, "Its TMDB ID"),
    Field("version", "4K", "4K for UHD, 1080p for Blu-ray, nothing for DVD"),
)
_TV = (
    Field("show", "Firefly", "The series' name on TMDB"),
    Field("year", 2002, "The year it first aired"),
    Field("tmdb_id", 1437, "Its TMDB ID"),
    Field("season", 1, "The season number (0 for specials)"),
    Field("episode", 2, "The episode number in its season"),
    Field("episode_title", "The Train Job", "The episode's title, if it has one"),
)


def _music(disc_total: int) -> tuple[Field, ...]:
    return (
        Field("artist", "Queen", "The album artist"),
        Field("album", "Greatest Hits", "The album title"),
        Field("year", 1981, "The release year"),
        Field("track", 1, "The track number on its disc"),
        Field("track_title", "Bohemian Rhapsody", "The track's title"),
        Field("track_artist", "Queen", "The track's artist"),
        Field("disc", 1, "The disc number"),
        Field("disc_total", disc_total, "How many discs the release has"),
        Field("disc_title", "", "The disc's own title, if it has one"),
    )


FIELDS: dict[Kind, tuple[Field, ...]] = {
    Kind.FILM: _FILM,
    Kind.TV: _TV,
    Kind.MUSIC_SINGLE_DISC: _music(1),
    Kind.MUSIC_MULTI_DISC: _music(2),
}

# Plex-friendly, and exactly the names AMA filed by before patterns could be edited.
DEFAULTS: dict[Kind, str] = {
    Kind.FILM: "{title} ({year}) {{tmdb-{tmdb_id}}}/{title} ({year}) {{tmdb-{tmdb_id}}} - {version}",
    Kind.TV: "{show} ({year}) {{tmdb-{tmdb_id}}}/Season {season:02}/"
             "{show} - s{season:02}e{episode:02} - {episode_title}",
    Kind.MUSIC_SINGLE_DISC: "{artist}/{album}/{track:02} - {track_title}",
    Kind.MUSIC_MULTI_DISC: "{artist}/{album}/{disc}{track:02} - {track_title}",
}


def examples(kind: Kind) -> dict[str, Value]:
    """Each field's example value, for a preview."""
    return {f.name: f.example for f in FIELDS[kind]}

# Each file's name is unique when the pattern has a field from every group.
_UNIQUE: dict[Kind, tuple[tuple[str, ...], ...]] = {
    Kind.FILM: (("title", "tmdb_id"), ("version",)),
    Kind.TV: (("show", "tmdb_id"), ("season",), ("episode",)),
    Kind.MUSIC_SINGLE_DISC: (("album",), ("track",)),
    Kind.MUSIC_MULTI_DISC: (("album",), ("disc",), ("track",)),
}
# Fields only the file name may use: a disc's tracks, cue, log and cover share one folder.
_FILE_ONLY: dict[Kind, frozenset[str]] = {
    Kind.MUSIC_SINGLE_DISC: frozenset({"track", "track_title", "track_artist"}),
    Kind.MUSIC_MULTI_DISC: frozenset({"track", "track_title", "track_artist"}),
}


class PatternError(ValueError):
    """A pattern that can't be used: what's wrong with it, for the editor."""


@dataclass(frozen=True)
class _Field:
    name: str
    width: int = 0  # `{track:02}`: zero-padded to 2

    def text(self, value: Value) -> str:
        return str(value).zfill(self.width)


_Token = str | _Field
_TOKEN = re.compile(r"\{\{|\}\}|\{([^{}]*)\}|[^{}]+|.")
_PLACEHOLDER = re.compile(r"([a-z_]+)(?::0([1-9]))?")
_ABSOLUTE = re.compile(r"^(?:[/\\]|[A-Za-z]:)")


def _parse(pattern: str) -> list[list[_Token]]:
    """The pattern's folder and file names as tokens. Raises PatternError."""
    if not pattern.strip():
        raise PatternError("The pattern is empty")
    if _ABSOLUTE.match(pattern):
        raise PatternError("The pattern must be relative to the Library's folder")
    segments = pattern.split("/")
    for s in segments:
        if not s.strip():
            raise PatternError("A folder or file name in the pattern is empty")
        if s.strip() in (".", ".."):
            raise PatternError(f"'{s.strip()}' can't be a folder name")
    return [_tokens(s) for s in segments]


def _tokens(segment: str) -> list[_Token]:
    out: list[_Token] = []
    for m in _TOKEN.finditer(segment):
        text = m.group(0)
        if m.group(1) is not None:
            p = _PLACEHOLDER.fullmatch(m.group(1))
            if not p:
                raise PatternError(f"{text} isn't a field: write {{name}}, or {{name:02}} "
                                   "to zero-pad, and {{ or }} for a brace")
            out.append(_Field(p.group(1), int(p.group(2) or 0)))
            continue
        if text in ("{", "}"):
            raise PatternError(f"A lone {text}: write {text}{text} for a brace")
        text = {"{{": "{", "}}": "}"}.get(text, text)
        if out and isinstance(out[-1], str):
            out[-1] += text
        else:
            out.append(text)
    return out


def _fields(segment: list[_Token]) -> list[_Field]:
    return [t for t in segment if isinstance(t, _Field)]


@dataclass(frozen=True)
class Check:
    """What the editor shows under a pattern: errors reject it, warnings don't."""

    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


def check(pattern: str, kind: Kind) -> Check:
    """Whether `pattern` can name every file of `kind`, uniquely."""
    try:
        segments = _parse(pattern)
    except PatternError as e:
        return Check(errors=(str(e),))
    known = {f.name for f in FIELDS[kind]}
    used = {f.name for seg in segments for f in _fields(seg)}
    errors = [f"{{{name}}} isn't a field here" for name in sorted(used - known)]
    for group in _UNIQUE[kind]:
        if not used & set(group):
            errors.append(f"Needs {' or '.join(f'{{{g}}}' for g in group)}, "
                          "so every file gets its own name")
    in_folders = {f.name for seg in segments[:-1] for f in _fields(seg)}
    for name in sorted(in_folders & _FILE_ONLY.get(kind, frozenset())):
        errors.append(f"{{{name}}} can only be in the file name")
    return Check(tuple(errors), tuple(_plex_warnings(kind, segments, used)))


def _plex_warnings(kind: Kind, segments: list[list[_Token]], used: set[str]) -> list[str]:
    if kind == Kind.FILM:
        return [f"Without {{{name}}}, Plex may match the wrong film"
                for name in ("year", "tmdb_id") if name not in used]
    if kind == Kind.TV and not _has_episode_form(segments[-1]):
        return ["Plex finds episodes by s01e02, 1x02 or 01x02 in the file name: "
                "write s{season:02}e{episode:02}"]
    return []


def _has_episode_form(segment: list[_Token]) -> bool:
    """`s{season}e{episode}` or `{season}x{episode}`, any case."""
    for i in range(len(segment) - 2):
        season, mid, episode = segment[i:i + 3]
        if not (isinstance(season, _Field) and season.name == "season"
                and isinstance(mid, str) and isinstance(episode, _Field)
                and episode.name == "episode"):
            continue
        prev = segment[i - 1] if i > 0 else ""
        if mid.lower() == "x" or (mid.lower() == "e" and isinstance(prev, str)
                                  and prev.lower().endswith("s")):
            return True
    return False


_SEPARATORS = " -–_.,·:;"
_ATTACHED_BEFORE = re.compile(r"\S*$")  # "(" in " ({year})"
_ATTACHED_AFTER = re.compile(r"^\S*")   # ")" in " ({year})"
_PART_BREAK = re.compile(r"( - |\s*\{[^{}]*\})")  # " - " and tags like " {tmdb-161}"


def _fill(segment: list[_Token], values: Mapping[str, Value]) -> str:
    """`segment` with its fields' values; an empty field drops out with the text attached
    to it and the separator before it (or after it, when nothing comes before)."""
    parts = [t if isinstance(t, str) else
             "" if values[t.name] is None else safe_chars(t.text(values[t.name])).strip()
             for t in segment]
    for i, t in enumerate(segment):
        if isinstance(t, str) or parts[i]:
            continue
        before = i > 0 and isinstance(segment[i - 1], str)
        after = i + 1 < len(segment) and isinstance(segment[i + 1], str)
        if before:
            parts[i - 1] = _ATTACHED_BEFORE.sub("", parts[i - 1], count=1)
        if after:
            parts[i + 1] = _ATTACHED_AFTER.sub("", parts[i + 1], count=1)
        if "".join(parts[:i]).strip(_SEPARATORS):
            if before:
                parts[i - 1] = parts[i - 1].rstrip(_SEPARATORS)
        elif after:
            parts[i + 1] = parts[i + 1].lstrip(_SEPARATORS)
    return "".join(parts)


def _safe(name: str) -> str:
    """`name` made safe part by part, as filing always has: `Title (Year)`, `Show`,
    `Episode` and `Track` each cut to the name limit, without trailing dots or a
    reserved name ("S.W.A.T - s01e01"); then the whole name (`archive.safe_name`)."""
    parts = _PART_BREAK.split(name)
    parts[::2] = [safe_name(p) if p.strip() else p for p in parts[::2]]
    return safe_name("".join(parts), SEGMENT_LIMIT)


def _render(pattern: str, kind: Kind, values: Mapping[str, Value], depth: int | None
            ) -> list[str]:
    segments = _parse(pattern)
    known = {f.name for f in FIELDS[kind]}
    for f in (f for seg in segments for f in _fields(seg)):
        if f.name not in known:
            raise PatternError(f"{{{f.name}}} isn't a field here")
    return [_safe(_fill(seg, values)) for seg in segments[:depth]]


def render(pattern: str, kind: Kind, values: Mapping[str, Value], ext: str) -> PurePosixPath:
    """Where a file named by `pattern` goes, relative to its Library's folder, each folder
    and file name made safe for Windows (`_safe`). Raises PatternError."""
    parts = _render(pattern, kind, values, None)
    parts[-1] += ext
    return PurePosixPath(*parts)


def folders(pattern: str, kind: Kind, values: Mapping[str, Value],
            depth: int | None = None) -> PurePosixPath:
    """The pattern's first `depth` folders (all of them by default), which need values
    only for the fields they use: a show's folder, without an Episode. Raises PatternError."""
    count = len(_parse(pattern)) - 1
    return PurePosixPath(*_render(pattern, kind, values, min(depth or count, count)))
