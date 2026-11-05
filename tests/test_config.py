import tomllib
from pathlib import Path
from typing import get_args, get_origin

import pytest
from pydantic import BaseModel

from ama.config import Config, ConfigError, load_config

EXAMPLE = Path(__file__).parent.parent / "ama.example.toml"


def _missing_keys(model: type[BaseModel], data: dict, prefix: str = "") -> list[str]:
    missing = []
    for name, field in model.model_fields.items():
        key = f"{prefix}{name}"
        if name not in data:
            missing.append(key)
        elif isinstance(field.annotation, type) and issubclass(field.annotation, BaseModel):
            missing += _missing_keys(field.annotation, data[name], key + ".")
        elif get_origin(field.annotation) is tuple:  # an array of tables: its first entry
            (item, *_) = get_args(field.annotation)
            missing += _missing_keys(item, data[name][0], key + "[0].")
    return missing


def test_example_config_documents_every_setting():
    data = tomllib.loads(EXAMPLE.read_text(encoding="utf-8"))
    assert _missing_keys(Config, data) == []


def test_example_config_mentions_each_secret_and_required_setting():
    text = EXAMPLE.read_text(encoding="utf-8").lower()
    for needle in ["tmdb", "plex", "token", "discord", "webhook", "ntfy", "topic",
                   "unc", "username", "password", "scratch", "cq"]:
        assert needle in text, needle


def test_example_config_loads(tmp_path):
    cfg = load_config(EXAMPLE)
    assert cfg.encode.cq.dvd > 0 and cfg.encode.cq.bd > 0 and cfg.encode.cq.uhd > 0
    assert cfg.web.password == ""  # example ships with auth off


def test_relative_paths_resolve_against_the_config_file(tmp_path):
    p = tmp_path / "ama.toml"
    text = EXAMPLE.read_text(encoding="utf-8")
    p.write_text(text.replace("scratch = 'D:\\ama-scratch'", "scratch = 'scratch'"),
                 encoding="utf-8")
    cfg = load_config(p)
    assert cfg.paths.state_db == tmp_path / "ama.sqlite3"
    assert cfg.paths.scratch == tmp_path / "scratch"


def test_misspelt_setting_is_rejected_with_its_name(tmp_path):
    p = tmp_path / "ama.toml"
    p.write_text(EXAMPLE.read_text(encoding="utf-8") + "\n[web2]\nport = 1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="web2"):
        load_config(p)


def test_missing_config_file_is_a_clear_error(tmp_path):
    with pytest.raises(ConfigError, match="ama.example.toml"):
        load_config(tmp_path / "nope.toml")


def test_an_existing_config_with_only_cq_gets_todays_encode_defaults(tmp_path):
    p = tmp_path / "ama.toml"
    text = EXAMPLE.read_text(encoding="utf-8")
    p.write_text(text[:text.index("[encode]")] + "[encode.cq]\ndvd = 20\nbd = 22\nuhd = 22\n",
                 encoding="utf-8")
    enc = load_config(p).encode
    assert (enc.encoder, enc.speed, enc.audio, enc.subtitles) == (
        "hevc_nvenc", "slower", "languages", "languages")
    assert enc.preferred_languages == ("en",)
    assert (enc.max_resolution.dvd, enc.max_resolution.bd, enc.max_resolution.uhd) == (
        "keep", "keep", "keep")


def _v1_config(tmp_path, letter: str, plex: str, webhook: str, ntfy: str) -> Path:
    text = EXAMPLE.read_text(encoding="utf-8")
    for old, new in [('letter = ""', f"letter = '{letter}'"),
                     ('url = "http://nas:32400"', f"url = '{plex}'"),
                     ('webhook_url = ""', f"webhook_url = '{webhook}'"),
                     ('url = "https://ntfy.sh"', f"url = '{ntfy}'")]:
        assert old in text, old
        text = text.replace(old, new)
    p = tmp_path / "ama.toml"
    p.write_text(text, encoding="utf-8")
    return p


@pytest.mark.parametrize("letter, want", [("D:\\", "D:"), ("D:", "D:"), ("d", "D:"),
                                          ("E:/", "E:"), ("", "")])
def test_startup_loads_a_v1_drive_letter_with_or_without_its_backslash(tmp_path, letter, want):
    cfg = load_config(_v1_config(tmp_path, letter, "http://nas:32400", "", "https://ntfy.sh"))
    assert cfg.drive.letter == want


def test_startup_loads_v1_addresses_without_a_scheme_or_a_discord_host(tmp_path):
    cfg = load_config(_v1_config(tmp_path, "", "192.168.1.10:32400",
                                 "https://hooks.example.net/notify/abc", "ntfy.example.org"))
    assert cfg.plex.url == "http://192.168.1.10:32400"  # Plex serves plain http locally
    assert cfg.ntfy.url == "https://ntfy.example.org"
    assert cfg.discord.webhook_url == "https://hooks.example.net/notify/abc"  # as v1 loaded it


def test_preferred_languages_take_names_or_codes_in_order():
    from ama.config import EncodeConfig
    cq = {"dvd": 20, "bd": 22, "uhd": 22}
    enc = EncodeConfig.model_validate({"cq": cq, "languages": "japanese, EN ,fra"})
    assert enc.preferred_languages == ("ja", "en", "fr")
    with pytest.raises(ValueError, match="Klingon"):
        EncodeConfig.model_validate({"cq": cq, "languages": "English, Klingon"})
    with pytest.raises(ValueError, match="at least one"):
        EncodeConfig.model_validate({"cq": cq, "languages": " , "})


def test_unknown_encode_choices_are_rejected():
    from pydantic import ValidationError

    from ama.config import EncodeConfig
    cq = {"dvd": 20, "bd": 22, "uhd": 22}
    for bad in ({"encoder": "h264_nvenc"}, {"speed": "ludicrous"}, {"audio": "some"},
                {"subtitles": "most"}, {"max_resolution": {"bd": "480p"}},
                {"max_resolution": {"dvd": "720p"}}):
        with pytest.raises(ValidationError):
            EncodeConfig.model_validate({"cq": cq, **bad})


# -- Libraries ---------------------------------------------------------------

def _with_libraries(tmp_path, libraries: list[tuple[str, str, str, bool]]) -> Path:
    """The example config with its Libraries replaced by (name, kind, path, default)."""
    text = EXAMPLE.read_text(encoding="utf-8").split("\n[[libraries]]")[0]
    for name, kind, path, default in libraries:
        text += (f"\n[[libraries]]\nname = \"{name}\"\nkind = \"{kind}\"\npath = '{path}'\n"
                 f"default = {str(default).lower()}\n")
    p = tmp_path / "ama.toml"
    p.write_text(text, encoding="utf-8")
    return p


SHARE = "\\\\nas\\media\\"


def test_the_example_has_a_default_library_per_kind():
    cfg = load_config(EXAMPLE)
    defaults = {lib.kind.value: lib.name for lib in cfg.libraries if lib.default}
    assert defaults == {"films": "Movies", "tv": "TV", "music": "Music"}


def test_a_kind_without_a_default_library_is_rejected(tmp_path):
    p = _with_libraries(tmp_path, [("Movies", "films", SHARE + "Movies", True),
                                   ("Music", "music", SHARE + "Music", True),
                                   ("Anime", "tv", SHARE + "Anime", False)])
    with pytest.raises(ConfigError, match="TV.*default"):
        load_config(p)


def test_two_defaults_of_one_kind_are_rejected(tmp_path):
    p = _with_libraries(tmp_path, [("Movies", "films", SHARE + "Movies", True),
                                   ("Movies 4K", "films", SHARE + "Movies 4K", True),
                                   ("TV", "tv", SHARE + "TV", True),
                                   ("Music", "music", SHARE + "Music", True)])
    with pytest.raises(ConfigError, match="one default"):
        load_config(p)


def test_a_library_can_be_any_folder_not_just_one_on_the_nas_share(tmp_path):
    folders = ["D:\\Movies", "\\\\other\\tv", "M:\\"]
    p = _with_libraries(tmp_path, [("Movies", "films", folders[0], True),
                                   ("TV", "tv", folders[1], True),
                                   ("Music", "music", folders[2], True)])
    assert [lib.path for lib in load_config(p).libraries] == folders


def test_a_library_folder_must_be_a_full_path(tmp_path):
    p = _with_libraries(tmp_path, [("Movies", "films", "Movies", True),
                                   ("TV", "tv", "D:\\TV", True),
                                   ("Music", "music", "D:\\Music", True)])
    with pytest.raises(ConfigError, match="full folder path"):
        load_config(p)


def test_library_names_are_unique(tmp_path):
    p = _with_libraries(tmp_path, [("Media", "films", SHARE + "Movies", True),
                                   ("media", "tv", SHARE + "TV", True),
                                   ("Music", "music", SHARE + "Music", True)])
    with pytest.raises(ConfigError, match="Media"):
        load_config(p)


def test_without_libraries_each_kind_defaults_to_a_folder_in_the_users_home(tmp_path):
    home = Path.home()
    cfg = load_config(_with_libraries(tmp_path, []))
    assert {(lib.kind.value, lib.name, lib.path, lib.default) for lib in cfg.libraries} == {
        ("films", "Movies", str(home / "Videos" / "Movies"), True),
        ("tv", "TV", str(home / "Videos" / "TV"), True),
        ("music", "Music", str(home / "Music"), True)}
