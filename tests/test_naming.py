"""The Naming Pattern engine: patterns, validation, and the defaults reproducing today's names."""

from __future__ import annotations

from pathlib import PurePosixPath

import pytest

from ama.naming import DEFAULTS, FIELDS, Check, Kind, PatternError, check, examples, render

TV_OK = "{show}/Season {season:02}/{show} - s{season:02}e{episode:02}"
MUSIC_OK = "{artist}/{album}/{track:02} - {track_title}"


@pytest.mark.parametrize("pattern, kind", [
    ("", Kind.FILM),
    ("   ", Kind.FILM),
    ("/Movies/{title} - {version}", Kind.FILM),
    ("\\{title} - {version}", Kind.FILM),
    ("C:/{title} - {version}", Kind.FILM),
    ("../{title} - {version}", Kind.FILM),
    ("{title}//{title} - {version}", Kind.FILM),
    ("{title} - {version}/", Kind.FILM),
    ("{title - {version}", Kind.FILM),            # unbalanced brace
    ("{title} } - {version}", Kind.FILM),
    ("{title:>10} - {version}", Kind.FILM),       # only zero-padding from format syntax
    ("{title!r} - {version}", Kind.FILM),
    ("{title} - {version} {nope}", Kind.FILM),    # not a film field
    ("{title}", Kind.FILM),                       # a film's BD and UHD versions would collide
    ("{year} - {version}", Kind.FILM),            # two films of a year would collide
    ("{show}/Season {season:02}/{show} - s{season:02}", Kind.TV),     # TV without {episode}
    ("{show}/{show} - e{episode:02}", Kind.TV),                       # ...or {season}
    ("Season {season:02}/s{season:02}e{episode:02}", Kind.TV),        # ...or the show
    ("{artist}/{album}/{track_title}", Kind.MUSIC_SINGLE_DISC),       # music without {track}
    ("{artist}/{track:02} - {track_title}", Kind.MUSIC_SINGLE_DISC),  # ...or {album}
    (MUSIC_OK, Kind.MUSIC_MULTI_DISC),                                # multi-disc without {disc}
    ("{artist}/{album}/{track:02}/{track_title}", Kind.MUSIC_SINGLE_DISC),  # one folder a disc
])
def test_validation_rejects_a_pattern_that_cant_name_every_file_uniquely(pattern, kind):
    assert check(pattern, kind).errors


@pytest.mark.parametrize("pattern, kind", [
    ("{title} ({year}) {{tmdb-{tmdb_id}}}/{title} ({year}) {{tmdb-{tmdb_id}}} - {version}",
     Kind.FILM),
    ("{tmdb_id} {version}", Kind.FILM),
    (TV_OK, Kind.TV),
    (MUSIC_OK, Kind.MUSIC_SINGLE_DISC),
    ("{artist}/{album}/{disc}{track:02} - {track_title}", Kind.MUSIC_MULTI_DISC),
])
def test_validation_accepts_a_pattern_naming_every_file_uniquely(pattern, kind):
    assert check(pattern, kind).errors == ()


@pytest.mark.parametrize("pattern, kind", [
    ("{title}/{title} - {version}", Kind.FILM),                        # no year or TMDB ID
    ("{title} ({year})/{title} ({year}) - {version}", Kind.FILM),     # no TMDB ID
    ("{title} {{tmdb-{tmdb_id}}}/{title} - {version}", Kind.FILM),    # no year
    ("{show}/Season {season}/{show} - {season}-{episode}", Kind.TV),  # no s01e02 form
    ("{show}/Season {season:02}/{show} - s{season:02}e{episode:02}/x{episode}", Kind.TV),
])
def test_validation_warns_without_rejecting_when_plex_wont_recognise_the_names(pattern, kind):
    result = check(pattern, kind)
    assert result.errors == ()
    assert result.warnings


@pytest.mark.parametrize("pattern", [
    "{show}/Season {season:02}/{show} - s{season:02}e{episode:02} - {episode_title}",
    "{show}/{show} S{season:02}E{episode:02}",
    "{show}/{show} {season}x{episode:02}",
    "{show}/{show} {season:02}x{episode:02}",
])
def test_plex_episode_forms_raise_no_warning(pattern):
    assert check(pattern, Kind.TV) == Check()


def test_every_field_of_each_kind_is_listed_with_an_example_for_the_editor():
    assert {f.name for f in FIELDS[Kind.FILM]} == {"title", "year", "tmdb_id", "version"}
    assert {f.name for f in FIELDS[Kind.TV]} == {
        "show", "year", "tmdb_id", "season", "episode", "episode_title"}
    music = {"artist", "album", "year", "track", "track_title", "track_artist", "disc",
             "disc_total", "disc_title"}
    assert {f.name for f in FIELDS[Kind.MUSIC_SINGLE_DISC]} == music
    assert {f.name for f in FIELDS[Kind.MUSIC_MULTI_DISC]} == music
    assert all(f.about for fields in FIELDS.values() for f in fields)


def test_the_defaults_pass_validation_and_preview_with_the_examples():
    assert all(check(DEFAULTS[k], k) == Check() for k in Kind)
    assert [str(render(DEFAULTS[k], k, examples(k), "")) for k in Kind] == [
        "Ocean's Eleven (2001) {tmdb-161}/Ocean's Eleven (2001) {tmdb-161} - 4K",
        "Firefly (2002) {tmdb-1437}/Season 01/Firefly - s01e02 - The Train Job",
        "Queen/Greatest Hits/01 - Bohemian Rhapsody",
        "Queen/Greatest Hits/101 - Bohemian Rhapsody",
    ]


def test_rendering_a_pattern_that_cant_be_parsed_or_uses_another_kinds_field_is_an_error():
    with pytest.raises(PatternError):
        render("{title", Kind.FILM, examples(Kind.FILM), "")
    with pytest.raises(PatternError):
        render("{show} - {version}", Kind.FILM, examples(Kind.FILM), "")


def test_a_pattern_is_literal_text_and_fields_with_slashes_between_folders():
    assert render("{artist}/{album}/{track_title}", Kind.MUSIC_SINGLE_DISC,
                  {"artist": "Queen", "album": "Greatest Hits", "track_title": "Bohemian Rhapsody"},
                  ".flac") == PurePosixPath("Queen/Greatest Hits/Bohemian Rhapsody.flac")


def test_fields_can_be_zero_padded_and_doubled_braces_are_literal():
    assert render("{show} {{tmdb-{tmdb_id}}}/Season {season:02}/s{season:02}e{episode:02}",
                  Kind.TV, {"show": "Firefly", "tmdb_id": 1437, "season": 1, "episode": 103},
                  ".mkv") == PurePosixPath("Firefly {tmdb-1437}/Season 01/s01e103.mkv")


def test_an_empty_field_drops_out_with_its_separators():
    def film(pattern: str, **values) -> str:
        return render(pattern, Kind.FILM, {"title": "Ocean's Eleven", "year": 2001,
                                            "tmdb_id": 161, "version": "4K"} | values, "").name

    assert film("{title} - {version}", version="") == "Ocean's Eleven"
    assert film("{title} ({year}) {{tmdb-{tmdb_id}}}", year=None) == "Ocean's Eleven {tmdb-161}"
    assert film("{title} ({year}) {{tmdb-{tmdb_id}}}", tmdb_id="") == "Ocean's Eleven (2001)"
    assert film("{version} - {title}", version="") == "Ocean's Eleven"
    assert film("{title} [{version}] ({year})", version="") == "Ocean's Eleven (2001)"
    assert film("{title} ({year})", year=0) == "Ocean's Eleven (0)"  # zero isn't empty


def test_each_segment_is_made_safe_for_windows():
    def music(**values) -> PurePosixPath:
        return render("{artist}/{album}/{track:02} - {track_title}", Kind.MUSIC_SINGLE_DISC,
                      {"artist": "Queen", "album": "Greatest Hits", "track": 1,
                       "track_title": "Bohemian Rhapsody"} | values, ".flac")

    assert music(album="AC/DC: Live?") == PurePosixPath(
        "Queen/AC_DC_ Live_/01 - Bohemian Rhapsody.flac")          # never an extra folder
    assert music(album="CON").parts[1] == "CON_"                     # reserved names
    assert music(album="Album.").parts[1] == "Album"                 # no trailing dot
    assert music(track_title="Done.").name == "01 - Done.flac"
    assert music(album="").parts[1] == "_"                           # never an empty folder
    assert music(album="x" * 200).parts[1] == "x" * 80               # length limit per field
    long = music(artist="a" * 100, album="b" * 100, track_title="c" * 100)
    assert long == PurePosixPath("a" * 80, "b" * 80, f"01 - {'c' * 80}.flac")
