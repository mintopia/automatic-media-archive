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
