"""Settings edits write ama.toml in place (ADR 0008): the file stays the one source of truth."""

from pathlib import Path

import pytest

from ama.config import ConfigError, LibraryKind, load_config
from ama.settings import SettingsFile, SettingsRejected, upgrade
from tests.conftest import make_harness, write_config

EXAMPLE = Path(__file__).parent.parent / "ama.example.toml"


@pytest.fixture
def toml(tmp_path) -> Path:
    p = tmp_path / "ama.toml"
    p.write_bytes(EXAMPLE.read_bytes())
    return p


def test_saving_changes_only_that_value_and_keeps_comments_and_order(toml):
    before = toml.read_text(encoding="utf-8")
    SettingsFile(toml).save({"web.port": "8081", "web.host": "0.0.0.0"})
    after = toml.read_text(encoding="utf-8")
    assert after == before.replace("port = 8080", "port = 8081")


def test_saving_keeps_the_previous_file_as_one_bak(toml):
    original = toml.read_bytes()
    SettingsFile(toml).save({"web.port": "8081"})
    assert toml.with_name("ama.toml.bak").read_bytes() == original
    SettingsFile(toml).save({"web.port": "8082"})
    assert b"port = 8081" in toml.with_name("ama.toml.bak").read_bytes()
    assert sorted(p.name for p in toml.parent.iterdir()) == ["ama.toml", "ama.toml.bak"]


def test_invalid_input_is_rejected_per_field_and_the_file_is_unchanged(toml):
    original = toml.read_bytes()
    with pytest.raises(SettingsRejected) as e:
        SettingsFile(toml).save({"web.port": "eighty", "cd.retries": "0",
                                 "ntfy.url": "ntfy.sh", "drive.poll_seconds": "3"})
    assert set(e.value.errors) == {"web.port", "cd.retries", "ntfy.url"}
    assert e.value.errors["web.port"] == "Enter a whole number"
    assert e.value.errors["cd.retries"] == "Enter 1 or more"
    assert "https://" in e.value.errors["ntfy.url"]
    assert toml.read_bytes() == original
    assert not toml.with_name("ama.toml.bak").exists()


def test_a_v1_value_startup_accepts_doesnt_block_other_edits_but_is_checked_when_edited(toml):
    text = toml.read_text(encoding="utf-8")
    toml.write_text(text.replace('webhook_url = ""', "webhook_url = 'https://hooks.example.net/x'")
                    .replace('letter = ""', "letter = 'D:\\'"), encoding="utf-8")
    assert SettingsFile(toml).save({"web.port": "8081"}) == ["web.port"]
    assert SettingsFile(toml).save({"web.port": "8082",  # its form sends it back unchanged
                                    "discord.webhook_url": "https://hooks.example.net/x"})
    with pytest.raises(SettingsRejected) as e:
        SettingsFile(toml).save({"discord.webhook_url": "https://hooks.example.net/y",
                                 "drive.letter": "D:\\"})
    assert set(e.value.errors) == {"discord.webhook_url"}  # D:\ is a fine way to type D:


def test_a_ui_edit_equals_the_same_hand_edit(toml, tmp_path):
    hand = tmp_path / "hand" / "ama.toml"
    hand.parent.mkdir()
    hand.write_text(EXAMPLE.read_text(encoding="utf-8")
                    .replace("retries = 10", "retries = 12")
                    .replace("uhd = 22", "uhd = 18")
                    .replace("log_file = 'logs\\ama.log'", "log_file = 'logs\\other.log'"),
                    encoding="utf-8")
    SettingsFile(toml).save({"cd.retries": "12", "encode.cq.uhd": "18",
                             "paths.log_file": "logs\\other.log"})
    assert toml.read_text(encoding="utf-8") == hand.read_text(encoding="utf-8")
    ui, by_hand = load_config(toml), load_config(hand)
    assert ui.model_dump(exclude={"paths"}) == by_hand.model_dump(exclude={"paths"})


def test_a_key_missing_from_the_file_is_added_to_its_table(tmp_path):
    p = tmp_path / "ama.toml"
    p.write_text("# mine\n[cd]\noffset = 6  # my drive\n\n[paths]\nscratch = 's'\n\n"
                 "[encode.cq]\ndvd = 20\nbd = 22\nuhd = 22\n", encoding="utf-8")
    SettingsFile(p).save({"cd.retries": "30", "tmdb.api_key": "k3y"})
    cfg = load_config(p)
    assert cfg.cd.retries == 30 and cfg.tmdb.api_key == "k3y"
    assert p.read_text(encoding="utf-8").startswith("# mine\n[cd]\noffset = 6  # my drive\n")


def test_a_comment_after_the_edited_value_stays(tmp_path):
    p = tmp_path / "ama.toml"
    p.write_text(EXAMPLE.read_text(encoding="utf-8").replace("port = 8080", "port = 8080  # mine"),
                 encoding="utf-8")
    SettingsFile(p).save({"web.port": "9000"})
    assert "port = 9000  # mine\n" in p.read_text(encoding="utf-8")


def test_unchanged_values_are_not_rewritten(toml):
    before = toml.read_text(encoding="utf-8")
    SettingsFile(toml).save({"drive.poll_seconds": "3.0", "paths.state_db": "ama.sqlite3"})
    assert toml.read_text(encoding="utf-8") == before


# --- Libraries: each one saves on its own ------------------------------------------------

SHARE = "\\\\nas\\media\\"


def _libraries(p: Path) -> list[tuple[str, str, str, str, bool]]:
    return [(lib.kind.value, lib.name, lib.path, lib.plex, lib.default)
            for lib in load_config(p).libraries]


def test_adding_a_library_appends_it_and_keeps_the_rest_of_the_file(toml):
    before = toml.read_text(encoding="utf-8")
    SettingsFile(toml).save_library(LibraryKind.TV, None, {"name": "Anime", "plex": "Anime",
                                                    "path": SHARE + "Anime"})
    after = toml.read_text(encoding="utf-8")
    assert after.startswith(before.rstrip("\n"))
    assert after.endswith("\n[[libraries]]\nname = \"Anime\"\nkind = \"tv\"\n"
                          "path = '\\\\nas\\media\\Anime'\nplex = \"Anime\"\n")
    assert _libraries(toml)[-1] == ("tv", "Anime", SHARE + "Anime", "Anime", False)


def test_editing_a_library_changes_only_that_entry(toml):
    before = toml.read_text(encoding="utf-8")
    SettingsFile(toml).save_library(LibraryKind.TV, "TV", {"name": "Series", "plex": "TV Shows",
                                                    "path": SHARE + "Series"})
    assert toml.read_text(encoding="utf-8") == before.replace(
        'name = "TV"', 'name = "Series"').replace("media\\TV'", "media\\Series'")


def test_a_file_without_libraries_gets_the_defaults_it_was_using_written_out(tmp_path):
    p = tmp_path / "ama.toml"
    p.write_text(EXAMPLE.read_text(encoding="utf-8").split("\n[[libraries]]")[0],
                 encoding="utf-8")
    SettingsFile(p).save_library(LibraryKind.FILMS, None, {"name": "Movies 4K", "plex": "",
                                                    "path": SHARE + "Movies 4K"})
    home = Path.home()
    assert _libraries(p) == [("films", "Movies", str(home / "Videos" / "Movies"), "", True),
                             ("tv", "TV", str(home / "Videos" / "TV"), "", True),
                             ("music", "Music", str(home / "Music"), "", True),
                             ("films", "Movies 4K", SHARE + "Movies 4K", "", False)]


def test_a_library_can_be_any_folder(toml):
    SettingsFile(toml).save_library(LibraryKind.FILMS, None, {"name": "Films", "plex": "",
                                                       "path": "D:\Films"})
    assert _libraries(toml)[-1] == ("films", "Films", "D:\Films", "", False)


def test_make_default_moves_the_kinds_default(toml):
    f = SettingsFile(toml)
    f.save_library(LibraryKind.FILMS, None, {"name": "Movies 4K", "plex": "", "path": SHARE + "4K"})
    f.make_default("Movies 4K")
    assert [(name, d) for kind, name, _, _, d in _libraries(toml) if kind == "films"] == [
        ("Movies", False), ("Movies 4K", True)]


def test_a_default_cant_be_removed_but_another_library_can(toml):
    f = SettingsFile(toml)
    f.save_library(LibraryKind.FILMS, None, {"name": "Movies 4K", "plex": "", "path": SHARE + "4K"})
    with pytest.raises(SettingsRejected, match="default"):
        f.remove_library("Movies")
    f.remove_library("Movies 4K")
    assert [name for _, name, *_ in _libraries(toml)] == ["Movies", "TV", "Music"]


def test_a_library_that_doesnt_validate_names_its_fields_and_the_file_is_unchanged(toml):
    original = toml.read_bytes()
    f = SettingsFile(toml)
    with pytest.raises(SettingsRejected) as e:
        f.save_library(LibraryKind.FILMS, None, {"name": "tv", "plex": "", "path": "D:\\Films"})
    assert set(e.value.errors) == {"name"} and "TV" in e.value.errors["name"]
    with pytest.raises(SettingsRejected) as e:
        f.save_library(LibraryKind.FILMS, None, {"name": " ", "plex": "", "path": ""})
    assert e.value.errors == {"name": "This can't be empty", "path": "This can't be empty"}
    with pytest.raises(SettingsRejected) as e:
        f.save_library(LibraryKind.FILMS, None, {"name": "Films", "plex": "", "path": "Films"})
    assert set(e.value.errors) == {"path"} and "full folder path" in e.value.errors["path"]
    assert toml.read_bytes() == original


# --- the one-time rewrite to plain Library paths (ADR 0011) -------------------------------

V2 = r"""[nas]
unc = '\\nas\media'

[paths]
scratch = 'scratch'

[plex]
url = "http://nas:32400"
# Where Plex sees the share.
nas_path = "/volume1/media"

[encode.cq]
dvd = 20
bd = 22
uhd = 22
"""


def test_a_file_without_libraries_gets_them_on_the_nas_share_and_a_bak(tmp_path):
    p = tmp_path / "ama.toml"
    p.write_text(V2, encoding="utf-8")
    assert upgrade(p)
    assert p.with_name("ama.toml.bak").read_text(encoding="utf-8") == V2
    assert _libraries(p) == [("films", "Movies", SHARE + "Movies", "", True),
                             ("tv", "TV", SHARE + "TV", "", True),
                             ("music", "Music", SHARE + "Music", "", True)]
    after = p.read_text(encoding="utf-8")
    assert 'libraries_path = "/volume1/media"' in after and "nas_path" not in after
    assert "[nas]" not in after and "unc" not in after
    assert load_config(p).plex.libraries_path == "/volume1/media"


def test_the_nas_table_is_dropped_with_its_comments_and_credentials(tmp_path):
    p = tmp_path / "ama.toml"
    p.write_text("[cd]\noffset = 6\n\n[nas]\n# The share.\nunc = '\\\\nas\\media'\n"
                 "username = \"me\"\npassword = \"hunter2\"\nretry_seconds = 30\n\n"
                 "[paths]\nscratch = 'scratch'\n\n[encode.cq]\ndvd = 20\nbd = 22\nuhd = 22\n"
                 + "".join(f"\n[[libraries]]\nname = \"{k.folder}\"\nkind = \"{k.value}\"\n"
                           f"path = 'D:\\{k.folder}'\ndefault = true\n" for k in LibraryKind),
                 encoding="utf-8")
    assert upgrade(p)
    after = p.read_text(encoding="utf-8")
    assert after.startswith("[cd]\noffset = 6\n\n[paths]\n")
    assert "nas" not in after and "hunter2" not in after
    assert "hunter2" in p.with_name("ama.toml.bak").read_text(encoding="utf-8")
    assert load_config(p).cd.offset == 6


def test_each_library_points_at_the_same_folder_as_before(tmp_path):
    p = tmp_path / "ama.toml"
    p.write_text(V2 + "".join(
        f"\n[[libraries]]\nname = \"{n}\"\nkind = \"{k}\"\npath = '{path}'\ndefault = true\n"
        for n, k, path in (("Movies", "films", "Films"), ("TV", "tv", SHARE + "TV"),
                           ("Music", "music", "Audio\Music"))), encoding="utf-8")
    upgrade(p)
    assert [path for _, _, path, _, _ in _libraries(p)] == [
        SHARE + "Films", SHARE + "TV", SHARE + "Audio\Music"]


def test_running_the_rewrite_again_changes_nothing(tmp_path):
    p = tmp_path / "ama.toml"
    p.write_text(V2, encoding="utf-8")
    upgrade(p)
    once, bak = p.read_bytes(), p.with_name("ama.toml.bak").read_bytes()
    assert not upgrade(p)
    assert p.read_bytes() == once and p.with_name("ama.toml.bak").read_bytes() == bak


@pytest.mark.parametrize("unc", ["", "unc = ''\n"])
def test_relative_libraries_without_a_share_are_left_alone_with_a_clear_error(tmp_path, unc):
    p = tmp_path / "ama.toml"
    before = (f"[nas]\n{unc}\n[paths]\nscratch = 'scratch'\n\n"
              "[[libraries]]\nname = \"Movies\"\nkind = \"films\"\npath = 'Films'\n"
              "default = true\n")
    p.write_text(before, encoding="utf-8")
    for _ in range(2):  # nothing is stranded: it says the same until the file is fixed
        with pytest.raises(ConfigError, match=r"Films.*nas\.unc"):
            upgrade(p)
        assert p.read_text(encoding="utf-8") == before
    assert not p.with_name("ama.toml.bak").exists()


def test_the_example_needs_no_rewrite(toml):
    before = toml.read_bytes()
    assert not upgrade(toml)
    assert toml.read_bytes() == before


# --- the running app: live keys apply at once, the rest wait for a restart ---------------

@pytest.fixture
def app(tmp_path):
    return make_harness(tmp_path, config_file=write_config(tmp_path)).services


def test_live_keys_apply_without_a_restart(app):
    app.settings.save({"cd.offset": "6", "cd.retries": "20", "encode.cq.bd": "19",
                       "tmdb.api_key": "new-key", "ntfy.topic": "my-topic",
                       "discord.webhook_url": "https://discord.com/api/webhooks/1/abc"})
    assert app.cd.cfg.offset == 6 and app.cd.cfg.retries == 20
    assert app.movie_archive.encoder.cfg.cq.bd == 19
    assert app.tmdb.api_key == "new-key"
    assert sorted(ch.name for ch in app.notifier.channels) == ["Discord", "ntfy"]
    assert app.config.cd.offset == 6
    assert app.settings.pending() == []


def test_library_changes_apply_from_the_next_filing(app, tmp_path):
    app.settings.save_library(LibraryKind.MUSIC, None, {"name": "Lossless", "plex": "",
                                                 "path": str(tmp_path / "libraries" / "Lossless")})
    app.settings.make_default("Lossless")
    assert app.archive.folder(Path("Music/Artist")) == tmp_path / "libraries" / "Lossless" / "Artist"
    assert app.settings.pending() == []


def test_other_keys_save_and_wait_for_a_restart(app):
    app.settings.save({"web.port": "8081", "drive.poll_seconds": "3"})
    assert app.config.web.port == 8080 and app.config.drive.poll_seconds == 0.01
    assert app.settings.pending() == ["web.port", "drive.poll_seconds"]
    app.settings.save({"web.port": "8080"})
    assert app.settings.pending() == ["drive.poll_seconds"]


def test_a_hand_edit_is_picked_up_like_a_ui_edit(app):
    p = app.settings.file.path
    p.write_text(p.read_text(encoding="utf-8").replace('api_key = "tmdb-key"', 'api_key = "hand"')
                 .replace("port = 8080", "port = 9000"), encoding="utf-8")
    app.settings.refresh(force=True)
    assert app.tmdb.api_key == "hand"
    assert app.settings.pending() == ["web.port"]


def test_a_broken_hand_edit_keeps_the_running_values(app):
    p = app.settings.file.path
    p.write_text(p.read_text(encoding="utf-8").replace("offset = 667", "offset = 'x'"),
                 encoding="utf-8")
    app.settings.refresh(force=True)
    assert app.cd.cfg.offset == 667
    assert "cd.offset" in app.settings.problem


# -- Setup writes a new file through the same writer (ADR 0016) -----------------------

def test_create_writes_a_new_file_that_loads_with_the_given_values(tmp_path):
    path = tmp_path / "AMA" / "ama.toml"
    films = str(tmp_path / "Films")
    SettingsFile(path).create(
        {"paths.scratch": str(tmp_path / "scratch")},
        [{"name": "Movies", "kind": "films", "path": films, "default": True},
         {"name": "TV", "kind": "tv", "path": str(tmp_path / "TV"), "default": True},
         {"name": "Music", "kind": "music", "path": str(tmp_path / "Music"), "default": True}])
    cfg = load_config(path)
    assert cfg.paths.scratch == tmp_path / "scratch"
    assert (cfg.libraries[0].name, cfg.libraries[0].path) == ("Movies", films)
    assert f"path = '{films}'" in path.read_text(encoding="utf-8")  # literal, like the example
    assert sorted(p.name for p in path.parent.iterdir()) == ["ama.toml"]


def test_create_rejects_bad_values_per_field_and_writes_nothing(tmp_path):
    path = tmp_path / "ama.toml"
    with pytest.raises(SettingsRejected) as e:
        SettingsFile(path).create({"paths.scratch": "scratch", "web.port": "eighty"})
    assert e.value.errors == {"web.port": "Enter a whole number"}
    assert not path.exists()


def test_create_never_overwrites_an_existing_file(toml):
    before = toml.read_bytes()
    with pytest.raises(FileExistsError):
        SettingsFile(toml).create({"paths.scratch": "scratch"})
    assert toml.read_bytes() == before
