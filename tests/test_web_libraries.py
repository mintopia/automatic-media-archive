"""Settings › Archive › Libraries: Libraries grouped by kind, edited one at a time (#27)."""

import html
import re

import pytest
from fastapi.testclient import TestClient

from ama.app import create_app
from ama.config import load_config
from tests.conftest import make_harness, write_config

PAGE = "/settings/archive/libraries"


@pytest.fixture
def setup(tmp_path):
    root = tmp_path / "libraries"
    toml = write_config(tmp_path, extra="".join(
        f"\n[[libraries]]\nname = \"{name}\"\nkind = \"{kind}\"\npath = '{root / folder}'\n"
        f"plex = \"{plex}\"\n" + ("default = true\n" if default else "")
        for name, kind, folder, plex, default in [
            ("Movies", "films", "Movies", "Movies", True),
            ("Family Films", "films", "Family Films", "Family Films", False),
            ("TV", "tv", "TV", "TV Shows", True),
            ("Music", "music", "Music", "Music", True)]))
    h = make_harness(tmp_path, config_file=toml)
    h.web.plex_sections += [
        {"key": "5", "type": "show", "title": "TV Shows", "Location": []},
        {"key": "6", "type": "show", "title": "Anime", "Location": []},
        {"key": "8", "type": "movie", "title": "Family Films", "Location": []}]
    with TestClient(create_app(h.services)) as c:
        yield c, toml, h


def _page(client, query=""):
    r = client.get(PAGE + query)
    assert r.status_code == 200
    return html.unescape(r.text)


def _group(page, kind):
    """One kind's group: its heading to the next one's."""
    start = page.index(f"<h2>{kind}</h2>")
    nxt = page.find('<div class="grp-h">', start + 1)
    return page[start:nxt if nxt != -1 else None]


def _libraries(toml):
    return [(lib.kind.value, lib.name, lib.plex, lib.default) for lib in load_config(toml).libraries]


def test_libraries_are_grouped_by_kind_with_the_default_first_and_locked(setup):
    client, _, h = setup
    page = _page(client)
    assert "<h2>Plex connection</h2>" in page and "Connected" in page
    assert "Save Plex connection" in page and "Plex sees Libraries at" in page
    assert "Share path seen by Plex" not in page
    films = _group(page, "Films")
    assert "Default: Movies" in films
    assert films.index(">Movies<") < films.index(">Family Films<")
    movies, family = films.split('role="listitem"')[1:3]
    assert "Default, can't be removed" in movies and "Remove" not in movies
    assert 'aria-label="Make Family Films the Films default"' in family
    assert 'aria-label="Remove Family Films"' in family
    assert str(h.libraries_root / "Family Films") in family.replace("<wbr>", "")
    assert "Add Films Library" in films
    assert "Default: TV" in _group(page, "TV") and "TV Shows" in _group(page, "TV")
    assert "Add Music Library" in _group(page, "Music")


def test_a_long_folder_breaks_after_its_separators_not_mid_name(setup):
    client, _, h = setup
    family = _group(_page(client), "Films").split('role="listitem"')[2]
    path = family.split('<span class="path">')[1].split("</span>")[0]
    assert path.endswith("\\<wbr>Family Films")
    assert path.replace("<wbr>", "") == str(h.libraries_root / "Family Films")


def test_add_opens_an_empty_form_whose_plex_list_holds_only_that_kinds_libraries(setup):
    client, _, _ = setup
    tv = _group(_page(client, "?add=tv"), "TV")
    assert "New TV Library" in tv and "Add TV Library</button>" in tv
    options = re.findall(r"<option[^>]*>([^<]*)</option>", tv)
    assert options == ["TV Shows", "Anime"]
    assert "Plex's TV libraries" in tv
    assert 'id="lib-name" name="lib.name" value=""' in tv


def test_adding_a_library_saves_it_to_its_kind(setup):
    client, toml, h = setup
    r = client.post(PAGE + "/save", data={"lib.kind": "tv", "lib.name": "Anime",
                                          "lib.plex": "Anime",
                                          "lib.path": str(h.libraries_root / "Anime")},
                    follow_redirects=False)
    assert r.status_code == 303
    assert ("tv", "Anime", "Anime", False) in _libraries(toml)
    assert ">Anime<" in _group(_page(client), "TV")


def test_edit_opens_the_form_under_its_row_and_saves_that_library(setup):
    client, toml, h = setup
    films = _group(_page(client, "?edit=Family Films"), "Films")
    assert 'aria-label="Edit Family Films"' in films and "Save Library" in films
    assert f'value="{h.libraries_root / "Family Films"}"' in films
    assert re.search(r"<option selected>Family Films</option>", films)
    client.post(PAGE + "/save", data={"lib.original": "Family Films", "lib.kind": "films",
                                      "lib.name": "Kids", "lib.plex": "Movies",
                                      "lib.path": str(h.libraries_root / "Kids")})
    assert ("films", "Kids", "Movies", False) in _libraries(toml)


def test_a_rejected_library_keeps_the_form_open_with_its_messages(setup):
    client, toml, _ = setup
    before = toml.read_bytes()
    r = client.post(PAGE + "/save", data={"lib.kind": "films", "lib.name": "tv",
                                          "lib.plex": "Movies", "lib.path": "Films"})
    assert r.status_code == 422
    page = html.unescape(r.text)
    films = _group(page, "Films")
    assert "New Films Library" in films and 'value="Films"' in films
    assert "There's already a Library called TV" in films and "full folder path" in films
    assert toml.read_bytes() == before


def test_make_default_moves_the_default(setup):
    client, toml, _ = setup
    client.post(PAGE + "/default", data={"library": "Family Films"})
    assert [(n, d) for k, n, _, d in _libraries(toml) if k == "films"] == [
        ("Movies", False), ("Family Films", True)]
    films = _group(_page(client), "Films")
    assert "Default: Family Films" in films
    assert films.index(">Family Films<") < films.index(">Movies<")


def test_remove_confirms_inline_naming_the_default_jobs_fall_back_to(setup):
    client, toml, _ = setup
    films = _group(_page(client, "?remove=Family Films"), "Films")
    assert 'role="alertdialog"' in films and "Remove Family Films?" in films
    assert "go to Movies, the Films default" in films
    assert "data-focus" in films
    client.post(PAGE + "/remove", data={"library": "Family Films"})
    assert [n for _, n, _, _ in _libraries(toml)] == ["Movies", "TV", "Music"]
    cancelled = _group(_page(client, "?focus=Movies"), "Films")
    assert "alertdialog" not in cancelled


def test_a_default_cant_be_removed_even_by_a_crafted_post(setup):
    client, toml, _ = setup
    before = toml.read_bytes()
    r = client.post(PAGE + "/remove", data={"library": "Movies"})
    assert r.status_code == 422
    assert "make another Library the default first" in html.unescape(r.text)
    assert toml.read_bytes() == before


def test_without_plex_the_list_is_disabled_and_saving_still_works(setup):
    client, toml, h = setup
    h.web.plex_offline = True
    page = _page(client, "?edit=Family Films")
    assert "Can't reach Plex" in page
    films = _group(page, "Films")
    assert re.search(r'<select class="select" id="lib-plex"[^>]* disabled', films)
    assert "AMA couldn't reach Plex at http://plex:32400" in films
    client.post(PAGE + "/save", data={"lib.original": "Family Films", "lib.kind": "films",
                                      "lib.name": "Family", "lib.path": str(h.libraries_root / "F")})
    assert ("films", "Family", "Family Films", False) in _libraries(toml)  # Plex pick kept


# --- the Naming Pattern (#67) -----------------------------------------------------------------

FILMS_DEFAULT = "{title} ({year}) {{tmdb-{tmdb_id}}}/{title} ({year}) {{tmdb-{tmdb_id}}} - {version}"


def _pattern(client, kind, pattern):
    r = client.get(PAGE + "/pattern", params={"lib.kind": kind, "lib.pattern": pattern})
    assert r.status_code == 200
    return html.unescape(r.text)


def test_a_film_librarys_editor_shows_its_pattern_fields_presets_and_a_preview(setup):
    client, *_ = setup
    films = _group(_page(client, "?edit=Movies"), "Films")
    assert re.search(r'<input [^>]*id="lib-pattern" name="lib.pattern" value="'
                     + re.escape(FILMS_DEFAULT) + '"', films)
    for field, example in [("{title}", "Ocean's Eleven"), ("{year}", "2001"),
                           ("{tmdb_id}", "161"), ("{version}", "4K")]:
        assert re.search(re.escape(field) + r"</code>.*?" + re.escape(example), films, re.S)
    assert 'data-preset="{title} ({year})/{title} ({year}) - {version}"' in films
    assert "Ocean's Eleven (2001) {tmdb-161}/Ocean's Eleven (2001) {tmdb-161} - 4K.mkv" in films
    tv = _group(_page(client, "?edit=TV"), "TV")
    assert 'id="lib-pattern"' not in tv  # TV and music patterns come later (#68, #69)


def test_the_preview_follows_the_pattern_with_its_errors_and_plex_warnings(setup):
    client, *_ = setup
    out = _pattern(client, "films", "{title}/{title} - {version}")
    assert "Ocean's Eleven/Ocean's Eleven - 4K.mkv" in out
    assert "Without {year}, Plex may match the wrong film" in out
    assert "Without {tmdb_id}, Plex may match the wrong film" in out
    bad = _pattern(client, "films", "{title}/{nope}")
    assert "{nope} isn't a field here" in bad and "Needs {version}" in bad
    assert ".mkv" not in bad  # no preview of a pattern that can't be used


def test_saving_a_pattern_files_later_films_by_it_and_a_bad_one_is_shown_again(setup):
    client, toml, h = setup
    data = {"lib.original": "Movies", "lib.kind": "films", "lib.name": "Movies",
            "lib.plex": "Movies", "lib.path": str(h.libraries_root / "Movies")}
    good = "{title} ({year})/{title} - {version}"
    r = client.post(PAGE + "/save", data=data | {"lib.pattern": good}, follow_redirects=False)
    assert r.status_code == 303
    assert load_config(toml).libraries[0].pattern == good
    r = client.post(PAGE + "/save", data=data | {"lib.pattern": "{title}"})
    assert r.status_code == 422
    films = _group(html.unescape(r.text), "Films")
    assert re.search(r'id="lib-pattern"[^>]*value="\{title\}"[^>]*aria-invalid="true"', films)
    assert "Needs {version}, so every file gets its own name" in films
    assert load_config(toml).libraries[0].pattern == good


# --- music's single-disc and multi-disc patterns (#69) ---------------------------------------

def test_a_music_librarys_editor_has_both_patterns_each_with_its_preview(setup):
    client, *_ = setup
    music = _group(_page(client, "?edit=Music"), "Music")
    assert re.search(r'<input [^>]*id="lib-pattern" name="lib.pattern" value="'
                     + re.escape("{artist}/{album}/{track:02} - {track_title}") + '"', music)
    assert re.search(r'<input [^>]*id="lib-multi_disc_pattern" name="lib.multi_disc_pattern" '
                     'value="' + re.escape("{artist}/{album}/{disc}{track:02} - {track_title}")
                     + '"', music)
    assert "Single-disc pattern" in music and "Multi-disc pattern" in music
    for field in ("artist", "album", "year", "track", "track_title", "track_artist", "disc",
                  "disc_total", "disc_title"):
        assert "{" + field + "}</code>" in music
    assert "Queen/Greatest Hits/01 - Bohemian Rhapsody.flac" in music
    assert "Queen/Greatest Hits/101 - Bohemian Rhapsody.flac" in music
    assert 'data-preset="{artist}/{album}/Disc {disc}/{track:02} - {track_title}"' in music
    assert 'aria-controls="lib-multi_disc_pattern"' in music


def test_the_multi_disc_preview_follows_its_own_pattern(setup):
    client, *_ = setup
    r = client.get(PAGE + "/pattern", params={
        "lib.kind": "music", "key": "multi_disc_pattern",
        "lib.multi_disc_pattern": "{artist}/{album}/Disc {disc}/{track:02} {track_title}"})
    assert r.status_code == 200
    assert "Queen/Greatest Hits/Disc 1/01 Bohemian Rhapsody.flac" in html.unescape(r.text)
    single = _pattern(client, "music", "{artist}/{album}/{track:02} - {track_title}")
    assert "Queen/Greatest Hits/01 - Bohemian Rhapsody.flac" in single
    bad = client.get(PAGE + "/pattern", params={
        "lib.kind": "music", "key": "multi_disc_pattern",
        "lib.multi_disc_pattern": "{artist}/{album}/{track:02}"})
    assert "Needs {disc}" in html.unescape(bad.text)
    assert client.get(PAGE + "/pattern", params={
        "lib.kind": "films", "key": "multi_disc_pattern"}).status_code == 404


def test_saving_a_music_librarys_patterns_and_a_bad_one_is_shown_again(setup):
    client, toml, h = setup
    data = {"lib.original": "Music", "lib.kind": "music", "lib.name": "Music",
            "lib.plex": "Music", "lib.path": str(h.libraries_root / "Music"),
            "lib.pattern": "{artist}/{album}/{track:02} - {track_title}"}
    multi = "{artist}/{album}/Disc {disc}/{track:02} - {track_title}"
    r = client.post(PAGE + "/save", data=data | {"lib.multi_disc_pattern": multi},
                    follow_redirects=False)
    assert r.status_code == 303
    assert next(lib for lib in load_config(toml).libraries
                if lib.name == "Music").multi_disc_pattern == multi
    r = client.post(PAGE + "/save", data=data | {"lib.multi_disc_pattern": "{album}/{track}"})
    assert r.status_code == 422
    music = _group(html.unescape(r.text), "Music")
    assert re.search(r'id="lib-multi_disc_pattern"[^>]*value="\{album\}/\{track\}"[^>]*'
                     'aria-invalid="true"', music)
    assert "Needs {disc}, so every file gets its own name" in music
