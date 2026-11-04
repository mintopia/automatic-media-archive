"""The one config file (TOML, untracked; `ama.example.toml` is the checked-in template).

Parsed once at startup into frozen pydantic models. Unknown keys are errors so
a typo can't silently fall back to a default. Every setting must also appear in
`ama.example.toml` (enforced by tests/test_config.py).
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _secret() -> str:
    return Field(default="", repr=False)  # type: ignore[return-value]


class WebConfig(_Section):
    host: str = "0.0.0.0"
    port: int = 8080
    password: str = _secret()


class DriveConfig(_Section):
    letter: str = ""
    poll_seconds: float = Field(default=3.0, gt=0)


class NasConfig(_Section):
    unc: str
    username: str = ""
    password: str = _secret()
    retry_seconds: float = Field(default=60.0, gt=0)


class PathsConfig(_Section):
    scratch: Path
    state_db: Path = Path("ama.sqlite3")
    log_file: Path = Path("logs/ama.log")


class TmdbConfig(_Section):
    api_key: str = _secret()


class PlexConfig(_Section):
    url: str = ""
    token: str = _secret()


class DiscordConfig(_Section):
    webhook_url: str = _secret()


class NtfyConfig(_Section):
    url: str = "https://ntfy.sh"
    topic: str = _secret()


class CqConfig(_Section):
    dvd: int = Field(ge=0, le=51)
    bd: int = Field(ge=0, le=51)
    uhd: int = Field(ge=0, le=51)


class EncodeConfig(_Section):
    cq: CqConfig


class Config(_Section):
    web: WebConfig = WebConfig()
    drive: DriveConfig = DriveConfig()
    nas: NasConfig
    paths: PathsConfig
    tmdb: TmdbConfig = TmdbConfig()
    plex: PlexConfig = PlexConfig()
    discord: DiscordConfig = DiscordConfig()
    ntfy: NtfyConfig = NtfyConfig()
    encode: EncodeConfig


class ConfigError(Exception):
    pass


def load_config(path: Path) -> Config:
    path = Path(path).resolve()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(
            f"No config file at {path}. Copy ama.example.toml to ama.toml and fill it in."
        ) from None
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from None
    try:
        cfg = Config.model_validate(data)
    except ValidationError as e:
        problems = "; ".join(
            f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()
        )
        raise ConfigError(f"{path}: {problems}") from None
    base = path.parent
    paths = cfg.paths.model_copy(
        update={
            "scratch": base / cfg.paths.scratch,
            "state_db": base / cfg.paths.state_db,
            "log_file": base / cfg.paths.log_file,
        }
    )
    return cfg.model_copy(update={"paths": paths})
