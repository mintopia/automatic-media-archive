"""Naming Patterns: the rule a Library files names by (GLOSSARY).

A pattern is literal text and `{field}` placeholders; `/` separates folders, `{{` and
`}}` are literal braces, and `{track:02}` zero-pads (nothing else from Python's format
syntax). It is relative to the Library's folder and has no extension. A field with no
value drops out with the text around it: `{title} ({year})` with no year is `Title`.

What a pattern names is its `Subject` (a film, a TV Episode, a track of a single- or
multi-disc release); everything about naming one is its `Spec`. Text is checked with
`check` and parsed once into a `Pattern`, which renders names.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from functools import cache
from pathlib import PurePosixPath

from ama.archive import safe_chars, safe_name
from ama.config import Library, LibraryKind

SEGMENT_LIMIT = 240  # a whole folder or file name, under NTFS's 255 with room for an extension


class Subject(StrEnum):
    """What a pattern names: each has its own fields and default (`Spec`)."""

    FILM = "film"
    TV = "tv"
    MUSIC_SINGLE_DISC = "music_single_disc"
    MUSIC_MULTI_DISC = "music_multi_disc"

    @property
    def spec(self) -> Spec:
        return SPECS[self]


class PatternKey(StrEnum):
    """A Library key that can hold a pattern (the `Library` field of the same name)."""

    PATTERN = "pattern"
    MULTI_DISC_PATTERN = "multi_disc_pattern"


Value = str | int | None


@dataclass(frozen=True)
class Field:
    """A placeholder a pattern can use, as the editor lists it."""

    name: str
    example: Value
    about: str


@dataclass(frozen=True)
class Preset:
    """A starting point the editor offers."""

    label: str
    pattern: str


@dataclass(frozen=True)
class Spec:
    """Everything about naming one Subject."""

    fields: tuple[Field, ...]
    # Plex-friendly, and exactly the names AMA filed by before patterns could be edited.
    default: str
    extension: str  # a named file's, for the editor's preview
    # Each file's name is unique when the pattern has a field from every group.
    unique: tuple[tuple[str, ...], ...]
    presets: tuple[Preset, ...] = ()
    # More examples the preview names, each the main one (`examples`) with these values.
    variants: tuple[Mapping[str, Value], ...] = ()
    # What the editor's errors call the pattern ("pattern" when a Library has only one),
    # and the editor's heading for it.
    label: str = "pattern"
    title: str = "Naming pattern"
    # Fields only the file name may use: a disc's tracks, cue, log and cover share one folder.
    file_only: frozenset[str] = frozenset()

    @property
    def examples(self) -> dict[str, Value]:
        """Each field's example value, for a preview."""
        return {f.name: f.example for f in self.fields}


def _music_fields(disc_total: int) -> tuple[Field, ...]:
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


_FILM_DEFAULT = ("{title} ({year}) {{tmdb-{tmdb_id}}}/"
                 "{title} ({year}) {{tmdb-{tmdb_id}}} - {version}")
_TV_DEFAULT = ("{show} ({year}) {{tmdb-{tmdb_id}}}/Season {season:02}/"
               "{show} - s{season:02}e{episode:02} - {episode_title}")
_SINGLE_DISC_DEFAULT = "{artist}/{album}/{track:02} - {track_title}"
_MULTI_DISC_DEFAULT = "{artist}/{album}/{disc}{track:02} - {track_title}"
_TRACK_FIELDS = frozenset({"track", "track_title", "track_artist"})

SPECS: dict[Subject, Spec] = {
    Subject.FILM: Spec(
        fields=(
            Field("title", "Ocean's Eleven", "The film's title on TMDB"),
            Field("year", 2001, "Its release year"),
            Field("tmdb_id", 161, "Its TMDB ID"),
            Field("version", "4K", "4K for UHD, 1080p for Blu-ray, nothing for DVD"),
        ),
        default=_FILM_DEFAULT,
        extension=".mkv",
        unique=(("title", "tmdb_id"), ("version",)),
        presets=(
            Preset("Plex, with the TMDB ID (default)", _FILM_DEFAULT),
            Preset("Plex, title and year", "{title} ({year})/{title} ({year}) - {version}"),
            Preset("By year", "{year}/{title} ({year})/{title} ({year}) - {version}"),
        ),
    ),
    Subject.TV: Spec(
        fields=(
            Field("show", "Firefly", "The series' name on TMDB"),
            Field("year", 2002, "The year it first aired"),
            Field("tmdb_id", 1437, "Its TMDB ID"),
            Field("season", 1, "The season number (0 for specials)"),
            Field("episode", 2, "The episode number in its season"),
            Field("episode_title", "The Train Job", "The episode's title, if it has one"),
        ),
        default=_TV_DEFAULT,
        extension=".mkv",
        unique=(("show", "tmdb_id"), ("season",), ("episode",)),
        presets=(
            Preset("Plex, with the TMDB ID (default)", _TV_DEFAULT),
            Preset("Plex, show name only",
                   "{show}/Season {season:02}/"
                   "{show} - s{season:02}e{episode:02} - {episode_title}"),
            Preset("No season folders",
                   "{show} ({year}) {{tmdb-{tmdb_id}}}/"
                   "{show} - s{season:02}e{episode:02} - {episode_title}"),
        ),
        variants=({"season": 0, "episode": 1,
                   "episode_title": "Here's How It Was: The Making of Firefly"},
                  {"episode": 3, "episode_title": ""}),
    ),
    Subject.MUSIC_SINGLE_DISC: Spec(
        fields=_music_fields(1),
        default=_SINGLE_DISC_DEFAULT,
        extension=".flac",
        unique=(("album",), ("track",)),
        presets=(
            Preset("Artist / Album (default)", _SINGLE_DISC_DEFAULT),
            Preset("Artist / Album (Year)",
                   "{artist}/{album} ({year})/{track:02} - {track_title}"),
        ),
        label="single-disc pattern",
        title="Single-disc pattern",
        file_only=_TRACK_FIELDS,
    ),
    Subject.MUSIC_MULTI_DISC: Spec(
        fields=_music_fields(2),
        default=_MULTI_DISC_DEFAULT,
        extension=".flac",
        unique=(("album",), ("disc",), ("track",)),
        presets=(
            Preset("Disc number before the track (default)", _MULTI_DISC_DEFAULT),
            Preset("A folder per disc",
                   "{artist}/{album}/Disc {disc}/{track:02} - {track_title}"),
            Preset("Disc-track", "{artist}/{album}/{disc}-{track:02} - {track_title}"),
        ),
        label="multi-disc pattern",
        title="Multi-disc pattern",
        file_only=_TRACK_FIELDS,
    ),
}

# The Libraries whose patterns Settings edits: each key, and what it names.
_SLOTS: dict[LibraryKind, dict[PatternKey, Subject]] = {
    LibraryKind.FILMS: {PatternKey.PATTERN: Subject.FILM},
    LibraryKind.TV: {PatternKey.PATTERN: Subject.TV},
    LibraryKind.MUSIC: {PatternKey.PATTERN: Subject.MUSIC_SINGLE_DISC,
                        PatternKey.MULTI_DISC_PATTERN: Subject.MUSIC_MULTI_DISC},
}


def patterns(kind: LibraryKind) -> dict[PatternKey, Subject]:
    """A `kind` Library's pattern keys and what each names; empty if it has none."""
    return dict(_SLOTS.get(kind, {}))


class PatternError(ValueError):
    """A pattern that can't be used: what's wrong with it, for the editor."""


@dataclass(frozen=True)
class _Placeholder:
    name: str
    width: int = 0  # `{track:02}`: zero-padded to 2

    def text(self, value: Value) -> str:
        return str(value).zfill(self.width)


_Token = str | _Placeholder
_Segment = tuple[_Token, ...]  # a folder or file name
_TOKEN = re.compile(r"\{\{|\}\}|\{([^{}]*)\}|[^{}]+|.")
_PLACEHOLDER = re.compile(r"([a-z_]+)(?::0([1-9]))?")
_ABSOLUTE = re.compile(r"^(?:[/\\]|[A-Za-z]:)")


def _segments(pattern: str) -> tuple[_Segment, ...]:
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
    return tuple(_tokens(s) for s in segments)


def _tokens(segment: str) -> _Segment:
    out: list[_Token] = []
    for m in _TOKEN.finditer(segment):
        text = m.group(0)
        if m.group(1) is not None:
            p = _PLACEHOLDER.fullmatch(m.group(1))
            if not p:
                raise PatternError(f"{text} isn't a field: write {{name}}, or {{name:02}} "
                                   "to zero-pad, and {{ or }} for a brace")
            out.append(_Placeholder(p.group(1), int(p.group(2) or 0)))
            continue
        if text in ("{", "}"):
            raise PatternError(f"A lone {text}: write {text}{text} for a brace")
        text = {"{{": "{", "}}": "}"}.get(text, text)
        if out and isinstance(out[-1], str):
            out[-1] += text
        else:
            out.append(text)
    return tuple(out)


def _placeholders(segment: _Segment) -> list[_Placeholder]:
    return [t for t in segment if isinstance(t, _Placeholder)]


def _used(segments: tuple[_Segment, ...]) -> set[str]:
    return {f.name for seg in segments for f in _placeholders(seg)}


def _unknown(subject: Subject, used: set[str]) -> list[str]:
    known = {f.name for f in subject.spec.fields}
    return [f"{{{name}}} isn't a field here" for name in sorted(used - known)]


@dataclass(frozen=True)
class Pattern:
    """A pattern parsed for its Subject: every field it uses is one of the Subject's."""

    text: str
    subject: Subject
    segments: tuple[_Segment, ...]

    @classmethod
    def parse(cls, text: str, subject: Subject) -> Pattern:
        """Raises PatternError if `text` can't be parsed or uses another Subject's field."""
        segments = _segments(text)
        if unknown := _unknown(subject, _used(segments)):
            raise PatternError(unknown[0])
        return cls(text, subject, segments)

    def render(self, values: Mapping[str, Value], ext: str) -> PurePosixPath:
        """Where a file it names goes, relative to its Library's folder, each folder and
        file name made safe for Windows (`_safe`)."""
        parts = self._names(values, None)
        parts[-1] += ext
        return PurePosixPath(*parts)

    def folders(self, values: Mapping[str, Value], depth: int | None = None) -> PurePosixPath:
        """Its first `depth` folders (all of them by default), which need values only for
        the fields they use: a show's folder, without an Episode."""
        count = len(self.segments) - 1
        return PurePosixPath(*self._names(values, min(depth or count, count)))

    def leading_folders(self, without: frozenset[str]) -> int:
        """How many of its first folders use none of the fields `without`: a TV pattern's
        season folder is as deep as its folders go before an Episode's own."""
        folders = self.segments[:-1]
        return next((i for i, seg in enumerate(folders)
                     if {f.name for f in _placeholders(seg)} & without), len(folders))

    def _names(self, values: Mapping[str, Value], depth: int | None) -> list[str]:
        return [_safe(_fill(seg, values)) for seg in self.segments[:depth]]


@cache
def default(subject: Subject) -> Pattern:
    """The Subject's default pattern, parsed."""
    return Pattern.parse(subject.spec.default, subject)


def pattern_of(library: Library, subject: Subject | None = None) -> Pattern:
    """The pattern `library` files `subject` by (by default, the one in its `pattern` key):
    its own, or the Subject's default when it has none."""
    slots = patterns(library.kind)
    key = (next((k for k, s in slots.items() if s == subject), None) if subject
           else PatternKey.PATTERN)
    if key not in slots:
        raise ValueError(f"{library.kind.label} Libraries have no editable pattern"
                         + (f" for {subject}" if subject else ""))
    own = getattr(library, key)
    return Pattern.parse(own, slots[key]) if own else default(slots[key])


@dataclass(frozen=True)
class Check:
    """What the editor shows under a pattern: errors reject it, warnings don't."""

    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


def check(pattern: str, subject: Subject) -> Check:
    """Whether `pattern` can name every file of `subject`, uniquely."""
    try:
        segments = _segments(pattern)
    except PatternError as e:
        return Check(errors=(str(e),))
    spec = subject.spec
    used = _used(segments)
    errors = _unknown(subject, used)
    for group in spec.unique:
        if not used & set(group):
            errors.append(f"Needs {' or '.join(f'{{{g}}}' for g in group)}, "
                          "so every file gets its own name")
    in_folders = _used(segments[:-1])
    for name in sorted(in_folders & spec.file_only):
        errors.append(f"{{{name}}} can only be in the file name")
    if subject == Subject.TV and not _is_show_folder(segments):
        errors.append("The first folder must be the show's, where its Extras go: "
                      "use {show} or {tmdb_id} in it, and no season or episode field")
    return Check(tuple(errors), tuple(_plex_warnings(subject, segments, used)))


def _is_show_folder(segments: tuple[_Segment, ...]) -> bool:
    """Whether the pattern's first folder names the show, and only the show."""
    if len(segments) < 2:
        return False
    used = {f.name for f in _placeholders(segments[0])}
    return bool(used & {"show", "tmdb_id"}) and not used & {"season", "episode", "episode_title"}


def _plex_warnings(subject: Subject, segments: tuple[_Segment, ...], used: set[str]
                   ) -> list[str]:
    if subject == Subject.FILM:
        return [f"Without {{{name}}}, Plex may match the wrong film"
                for name in ("year", "tmdb_id") if name not in used]
    if subject == Subject.TV and not _has_episode_form(segments[-1]):
        return ["Plex finds episodes by s01e02, 1x02 or 01x02 in the file name: "
                "write s{season:02}e{episode:02}"]
    return []


def _has_episode_form(segment: _Segment) -> bool:
    """`s{season}e{episode}` or `{season}x{episode}`, any case."""
    for i in range(len(segment) - 2):
        season, mid, episode = segment[i:i + 3]
        if not (isinstance(season, _Placeholder) and season.name == "season"
                and isinstance(mid, str) and isinstance(episode, _Placeholder)
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


def _fill(segment: _Segment, values: Mapping[str, Value]) -> str:
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
