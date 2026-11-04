import tomllib
from pathlib import Path

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
