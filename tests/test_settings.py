"""Settings edits write ama.toml in place (ADR 0008): the file stays the one source of truth."""

from pathlib import Path

import pytest

from ama.config import Kind, load_config
from ama.settings import SettingsFile, SettingsRejected
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
    p.write_text("# mine\n[nas]\nunc = '\\\\nas\\media'  # the share\n\n[paths]\nscratch = 's'\n\n"
                 "[encode.cq]\ndvd = 20\nbd = 22\nuhd = 22\n", encoding="utf-8")
    SettingsFile(p).save({"nas.retry_seconds": "30", "tmdb.api_key": "k3y"})
    cfg = load_config(p)
    assert cfg.nas.retry_seconds == 30 and cfg.tmdb.api_key == "k3y"
    assert p.read_text(encoding="utf-8").startswith(
        "# mine\n[nas]\nunc = '\\\\nas\\media'  # the share\n")


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
    SettingsFile(toml).save_library(Kind.TV, None, {"name": "Anime", "plex": "Anime",
                                                    "path": SHARE + "Anime"})
    after = toml.read_text(encoding="utf-8")
    assert after.startswith(before.rstrip("\n"))
    assert after.endswith("\n[[libraries]]\nname = \"Anime\"\nkind = \"tv\"\n"
                          "path = '\\\\nas\\media\\Anime'\nplex = \"Anime\"\n")
    assert _libraries(toml)[-1] == ("tv", "Anime", SHARE + "Anime", "Anime", False)


def test_editing_a_library_changes_only_that_entry(toml):
    before = toml.read_text(encoding="utf-8")
    SettingsFile(toml).save_library(Kind.TV, "TV", {"name": "Series", "plex": "TV Shows",
                                                    "path": SHARE + "Series"})
    assert toml.read_text(encoding="utf-8") == before.replace(
        'name = "TV"', 'name = "Series"').replace("media\\TV'", "media\\Series'")


def test_a_file_without_libraries_gets_the_defaults_it_was_using_written_out(tmp_path):
    p = tmp_path / "ama.toml"
    p.write_text(EXAMPLE.read_text(encoding="utf-8").split("\n[[libraries]]")[0],
                 encoding="utf-8")
    SettingsFile(p).save_library(Kind.FILMS, None, {"name": "Movies 4K", "plex": "",
                                                    "path": SHARE + "Movies 4K"})
    assert _libraries(p) == [("films", "Movies", SHARE + "Movies", "", True),
                             ("tv", "TV", SHARE + "TV", "", True),
                             ("music", "Music", SHARE + "Music", "", True),
                             ("films", "Movies 4K", SHARE + "Movies 4K", "", False)]


def test_make_default_moves_the_kinds_default(toml):
    f = SettingsFile(toml)
    f.save_library(Kind.FILMS, None, {"name": "Movies 4K", "plex": "", "path": SHARE + "4K"})
    f.make_default("Movies 4K")
    assert [(name, d) for kind, name, _, _, d in _libraries(toml) if kind == "films"] == [
        ("Movies", False), ("Movies 4K", True)]


def test_a_default_cant_be_removed_but_another_library_can(toml):
    f = SettingsFile(toml)
    f.save_library(Kind.FILMS, None, {"name": "Movies 4K", "plex": "", "path": SHARE + "4K"})
    with pytest.raises(SettingsRejected, match="default"):
        f.remove_library("Movies")
    f.remove_library("Movies 4K")
    assert [name for _, name, *_ in _libraries(toml)] == ["Movies", "TV", "Music"]


def test_a_library_that_doesnt_validate_names_its_fields_and_the_file_is_unchanged(toml):
    original = toml.read_bytes()
    f = SettingsFile(toml)
    with pytest.raises(SettingsRejected) as e:
        f.save_library(Kind.FILMS, None, {"name": "tv", "plex": "", "path": "D:\\Films"})
    assert set(e.value.errors) == {"name", "path"}
    assert "TV" in e.value.errors["name"] and "NAS share" in e.value.errors["path"]
    with pytest.raises(SettingsRejected) as e:
        f.save_library(Kind.FILMS, None, {"name": " ", "plex": "", "path": ""})
    assert e.value.errors == {"name": "This can't be empty", "path": "This can't be empty"}
    assert toml.read_bytes() == original


# --- the running app: live keys apply at once, the rest wait for a restart ---------------

@pytest.fixture
def app(tmp_path):
    return make_harness(tmp_path, config_file=write_config(tmp_path)).services


def test_live_keys_apply_without_a_restart(app):
    app.settings.save({"cd.offset": "6", "cd.retries": "20", "encode.cq.bd": "19",
                       "tmdb.api_key": "new-key", "ntfy.topic": "my-topic",
                       "discord.webhook_url": "https://discord.com/api/webhooks/1/abc"})
    assert app.cd.cfg.offset == 6 and app.cd.cfg.retries == 20
    assert app.movie_archive.encoder.cq.bd == 19
    assert app.tmdb.api_key == "new-key"
    assert sorted(ch.name for ch in app.notifier.channels) == ["Discord", "ntfy"]
    assert app.config.cd.offset == 6
    assert app.settings.pending() == []


def test_library_changes_apply_from_the_next_filing(app, tmp_path):
    app.settings.save_library(Kind.MUSIC, None, {"name": "Lossless", "plex": "",
                                                 "path": str(tmp_path / "nas" / "Lossless")})
    app.settings.make_default("Lossless")
    assert app.archive.folder(Path("Music/Artist")) == tmp_path / "nas" / "Lossless" / "Artist"
    assert app.settings.pending() == []


def test_other_keys_save_and_wait_for_a_restart(app):
    app.settings.save({"web.port": "8081", "nas.retry_seconds": "30"})
    assert app.config.web.port == 8080 and app.config.nas.retry_seconds == 0.05
    assert app.settings.pending() == ["web.port", "nas.retry_seconds"]
    app.settings.save({"web.port": "8080"})
    assert app.settings.pending() == ["nas.retry_seconds"]


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
