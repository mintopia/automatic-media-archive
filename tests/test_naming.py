"""The Naming Pattern engine: patterns, validation, and the defaults reproducing today's names."""

from __future__ import annotations

from pathlib import PurePosixPath

import pytest

from ama.naming import SPECS, Check, Pattern, PatternError, Subject, check

TV_OK = "{show}/Season {season:02}/{show} - s{season:02}e{episode:02}"
MUSIC_OK = "{artist}/{album}/{track:02} - {track_title}"


def render(text: str, subject: Subject, values, ext: str) -> PurePosixPath:
    return Pattern.parse(text, subject).render(values, ext)


@pytest.mark.parametrize("pattern, kind", [
    ("", Subject.FILM),
    ("   ", Subject.FILM),
    ("/Movies/{title} - {version}", Subject.FILM),
    ("\\{title} - {version}", Subject.FILM),
    ("C:/{title} - {version}", Subject.FILM),
    ("../{title} - {version}", Subject.FILM),
    ("{title}//{title} - {version}", Subject.FILM),
    ("{title} - {version}/", Subject.FILM),
    ("{title - {version}", Subject.FILM),            # unbalanced brace
    ("{title} } - {version}", Subject.FILM),
    ("{title:>10} - {version}", Subject.FILM),       # only zero-padding from format syntax
    ("{title!r} - {version}", Subject.FILM),
    ("{title} - {version} {nope}", Subject.FILM),    # not a film field
    ("{title}", Subject.FILM),                       # a film's BD and UHD versions would collide
    ("{year} - {version}", Subject.FILM),            # two films of a year would collide
    ("{show}/Season {season:02}/{show} - s{season:02}", Subject.TV),     # TV without {episode}
    ("{show}/{show} - e{episode:02}", Subject.TV),                       # ...or {season}
    ("Season {season:02}/s{season:02}e{episode:02}", Subject.TV),        # ...or the show
    ("{artist}/{album}/{track_title}", Subject.MUSIC_SINGLE_DISC),       # music without {track}
    ("{artist}/{track:02} - {track_title}", Subject.MUSIC_SINGLE_DISC),  # ...or {album}
    (MUSIC_OK, Subject.MUSIC_MULTI_DISC),                                # multi-disc without {disc}
    ("{artist}/{album}/{track:02}/{track_title}", Subject.MUSIC_SINGLE_DISC),  # one folder a disc
])
def test_validation_rejects_a_pattern_that_cant_name_every_file_uniquely(pattern, kind):
    assert check(pattern, kind).errors


@pytest.mark.parametrize("pattern, kind", [
    ("{title} ({year}) {{tmdb-{tmdb_id}}}/{title} ({year}) {{tmdb-{tmdb_id}}} - {version}",
     Subject.FILM),
    ("{tmdb_id} {version}", Subject.FILM),
    (TV_OK, Subject.TV),
    (MUSIC_OK, Subject.MUSIC_SINGLE_DISC),
    ("{artist}/{album}/{disc}{track:02} - {track_title}", Subject.MUSIC_MULTI_DISC),
])
def test_validation_accepts_a_pattern_naming_every_file_uniquely(pattern, kind):
    assert check(pattern, kind).errors == ()


@pytest.mark.parametrize("pattern, kind", [
    ("{title}/{title} - {version}", Subject.FILM),                        # no year or TMDB ID
    ("{title} ({year})/{title} ({year}) - {version}", Subject.FILM),     # no TMDB ID
    ("{title} {{tmdb-{tmdb_id}}}/{title} - {version}", Subject.FILM),    # no year
    ("{show}/Season {season}/{show} - {season}-{episode}", Subject.TV),  # no s01e02 form
    ("{show}/Season {season:02}/{show} - s{season:02}e{episode:02}/x{episode}", Subject.TV),
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
    assert check(pattern, Subject.TV) == Check()


def test_every_field_of_each_kind_is_listed_with_an_example_for_the_editor():
    assert {f.name for f in SPECS[Subject.FILM].fields} == {"title", "year", "tmdb_id", "version"}
    assert {f.name for f in SPECS[Subject.TV].fields} == {
        "show", "year", "tmdb_id", "season", "episode", "episode_title"}
    music = {"artist", "album", "year", "track", "track_title", "track_artist", "disc",
             "disc_total", "disc_title"}
    assert {f.name for f in SPECS[Subject.MUSIC_SINGLE_DISC].fields} == music
    assert {f.name for f in SPECS[Subject.MUSIC_MULTI_DISC].fields} == music
    assert all(f.about for spec in SPECS.values() for f in spec.fields)


def test_the_defaults_pass_validation_and_preview_with_the_examples():
    assert all(check(k.spec.default, k) == Check() for k in Subject)
    assert [str(render(k.spec.default, k, k.spec.examples, "")) for k in Subject] == [
        "Ocean's Eleven (2001) {tmdb-161}/Ocean's Eleven (2001) {tmdb-161} - 4K",
        "Firefly (2002) {tmdb-1437}/Season 01/Firefly - s01e02 - The Train Job",
        "Queen/Greatest Hits/01 - Bohemian Rhapsody",
        "Queen/Greatest Hits/101 - Bohemian Rhapsody",
    ]


def test_rendering_a_pattern_that_cant_be_parsed_or_uses_another_kinds_field_is_an_error():
    with pytest.raises(PatternError):
        render("{title", Subject.FILM, Subject.FILM.spec.examples, "")
    with pytest.raises(PatternError):
        render("{show} - {version}", Subject.FILM, Subject.FILM.spec.examples, "")


def test_a_pattern_is_literal_text_and_fields_with_slashes_between_folders():
    assert render("{artist}/{album}/{track_title}", Subject.MUSIC_SINGLE_DISC,
                  {"artist": "Queen", "album": "Greatest Hits", "track_title": "Bohemian Rhapsody"},
                  ".flac") == PurePosixPath("Queen/Greatest Hits/Bohemian Rhapsody.flac")


def test_fields_can_be_zero_padded_and_doubled_braces_are_literal():
    assert render("{show} {{tmdb-{tmdb_id}}}/Season {season:02}/s{season:02}e{episode:02}",
                  Subject.TV, {"show": "Firefly", "tmdb_id": 1437, "season": 1, "episode": 103},
                  ".mkv") == PurePosixPath("Firefly {tmdb-1437}/Season 01/s01e103.mkv")


def test_an_empty_field_drops_out_with_its_separators():
    def film(pattern: str, **values) -> str:
        return render(pattern, Subject.FILM, {"title": "Ocean's Eleven", "year": 2001,
                                            "tmdb_id": 161, "version": "4K"} | values, "").name

    assert film("{title} - {version}", version="") == "Ocean's Eleven"
    assert film("{title} ({year}) {{tmdb-{tmdb_id}}}", year=None) == "Ocean's Eleven {tmdb-161}"
    assert film("{title} ({year}) {{tmdb-{tmdb_id}}}", tmdb_id="") == "Ocean's Eleven (2001)"
    assert film("{version} - {title}", version="") == "Ocean's Eleven"
    assert film("{title} [{version}] ({year})", version="") == "Ocean's Eleven (2001)"
    assert film("{title} ({year})", year=0) == "Ocean's Eleven (0)"  # zero isn't empty


def test_each_segment_is_made_safe_for_windows():
    def music(**values) -> PurePosixPath:
        return render("{artist}/{album}/{track:02} - {track_title}", Subject.MUSIC_SINGLE_DISC,
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
