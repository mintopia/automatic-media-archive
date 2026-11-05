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


def test_a_library_outside_the_nas_share_is_rejected(tmp_path):
    p = _with_libraries(tmp_path, [("Movies", "films", "D:\\Movies", True),
                                   ("TV", "tv", SHARE + "TV", True),
                                   ("Music", "music", SHARE + "Music", True)])
    with pytest.raises(ConfigError, match="NAS share"):
        load_config(p)


def test_library_names_are_unique(tmp_path):
    p = _with_libraries(tmp_path, [("Media", "films", SHARE + "Movies", True),
                                   ("media", "tv", SHARE + "TV", True),
                                   ("Music", "music", SHARE + "Music", True)])
    with pytest.raises(ConfigError, match="Media"):
        load_config(p)


def test_without_libraries_each_kind_defaults_to_its_folder_on_the_share(tmp_path):
    cfg = load_config(_with_libraries(tmp_path, []))
    assert {(lib.kind.value, lib.name, lib.path, lib.default) for lib in cfg.libraries} == {
        ("films", "Movies", SHARE + "Movies", True),
        ("tv", "TV", SHARE + "TV", True),
        ("music", "Music", SHARE + "Music", True)}
