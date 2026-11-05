"""The one config file (TOML, untracked; `ama.example.toml` is the checked-in template).

Parsed at startup into frozen pydantic models; the Settings page validates its
edits through the same models (ADR 0008, `ama.settings`). Format checks (drive letter,
addresses, the Discord webhook) only reject a value the Settings page is saving; at startup
they normalize what they can ("D:\\" -> "D:", "nas:32400" -> "http://nas:32400") and keep
the rest, so every file v1 loaded still loads. Unknown keys are errors so
a typo can't silently fall back to a default. Every setting must also appear in
`ama.example.toml` (enforced by tests/test_config.py).
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Callable, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (AfterValidator, BaseModel, ConfigDict, Field, ValidationError,
                      ValidationInfo, model_validator)

from ama.languages import parse_languages


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _secret() -> str:
    return Field(default="", repr=False)


EDITED = "edited"  # validation context: the keys the Settings page is saving


def _edited(info: ValidationInfo, key: str) -> bool:
    """Whether the Settings page is saving `key`. Format checks only reject a value then:
    startup still loads every ama.toml v1 accepted (ADR 0008), normalized where it can be."""
    return isinstance(info.context, dict) and key in info.context.get(EDITED, ())


def _web_address(key: str, scheme: str) -> Callable[[str, ValidationInfo], str]:
    """An http(s) address; a bare host ("nas:32400") gets `scheme`, as v1 users typed it."""
    def check(value: str, info: ValidationInfo) -> str:
        value = value.strip()
        if value and "://" not in value and re.fullmatch(r"[\w.-]+(:\d+)?(/\S*)?", value) \
                and not _edited(info, key):
            value = f"{scheme}://{value}"
        if value and not value.startswith(("http://", "https://")) and _edited(info, key):
            raise ValueError("Enter a full address starting with https:// or http://")
        return value
    return check


def _discord_webhook(value: str, info: ValidationInfo) -> str:
    if value and _edited(info, "discord.webhook_url") and not re.match(
            r"https://(ptb\.|canary\.)?discord(app)?\.com/api/webhooks/", value):
        raise ValueError("Paste the whole webhook URL, starting with https://discord.com/api/webhooks/")
    return value


def _drive_letter(value: str, info: ValidationInfo) -> str:
    """"D", "d:", "D:\\" -> "D:"."""
    value = value.strip()
    m = re.fullmatch(r"([A-Za-z]):?[\\/]?", value)
    if m:
        return m.group(1).upper() + ":"
    if value and _edited(info, "drive.letter"):
        raise ValueError("Enter a drive letter like D:, or leave it empty")
    return value


class WebConfig(_Section):
    host: str = "0.0.0.0"
    port: int = Field(default=8080, ge=1, le=65535)
    password: str = _secret()


class DriveConfig(_Section):
    letter: Annotated[str, AfterValidator(_drive_letter)] = ""
    poll_seconds: float = Field(default=3.0, gt=0)


class ToolsConfig(_Section):
    """External programs (ADR 0006). Empty = AMA's default for that tool."""

    dir: str = ""  # where AMA keeps its portable tools; empty = %LOCALAPPDATA%\ama\tools
    ffmpeg: str = ""
    ffprobe: str = ""
    cyanrip: str = ""
    makemkvcon: str = ""


class CdConfig(_Section):
    offset: int = 667
    retries: int = Field(default=10, ge=1)


class PathsConfig(_Section):
    scratch: Path
    state_db: Path = Path("ama.sqlite3")
    log_file: Path = Path("logs/ama.log")


class ScratchConfig(_Section):
    """Free scratch (GB) a Disc of each Type needs before its Rip starts; less = refused.
    `retention_days`: Scratch cleanup removes kept Scratch older than this; 0 = never.
    `floor_gb`: below this much free, it removes kept Scratch of any age; 0 = off."""

    cd: int = Field(default=1, ge=0)
    dvd: int = Field(default=10, ge=0)
    bd: int = Field(default=50, ge=0)
    uhd: int = Field(default=100, ge=0)
    retention_days: int = Field(default=0, ge=0)
    floor_gb: int = Field(default=0, ge=0)


class MinTitleConfig(_Section):
    dvd: int = Field(default=30, ge=0)
    bd: int = Field(default=30, ge=0)
    uhd: int = Field(default=30, ge=0)


class RipConfig(_Section):
    """A video Title shorter than its Disc Type's `min_title_seconds` isn't ripped (ADR 0005)."""

    min_title_seconds: MinTitleConfig = MinTitleConfig()


class TmdbConfig(_Section):
    api_key: str = _secret()


class PlexConfig(_Section):
    url: Annotated[str, AfterValidator(_web_address("plex.url", "http"))] = ""
    token: str = _secret()
    # Where the Plex server sees the Libraries ("Plex sees Libraries at"): each Library
    # folder is <libraries_path>/<its folder name>. Empty = the same path as AMA.
    libraries_path: str = ""


class DiscordConfig(_Section):
    webhook_url: Annotated[str, AfterValidator(_discord_webhook)] = _secret()


class NtfyConfig(_Section):
    url: Annotated[str, AfterValidator(_web_address("ntfy.url", "https"))] = "https://ntfy.sh"
    topic: str = _secret()


def _header_name(value: str, info: ValidationInfo) -> str:
    value = value.strip()
    if value and _edited(info, "webhook.header_name") and not re.fullmatch(
            r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", value):
        raise ValueError("Use letters, digits and dashes only, like X-Ama-Token")
    return value


class WebhookConfig(_Section):
    """Alerts as versioned JSON POSTed to `url`; `header_name`/`header_value`, when both
    are set, go with every request (e.g. a token the receiver checks)."""

    url: Annotated[str, AfterValidator(_web_address("webhook.url", "https"))] = _secret()
    header_name: Annotated[str, AfterValidator(_header_name)] = ""
    header_value: str = _secret()


class LogsConfig(_Section):
    """Logs (#34): Step output older than `keep_days` is removed; 0 keeps it forever."""

    keep_days: int = Field(default=0, ge=0)


class CqConfig(_Section):
    dvd: int = Field(ge=0, le=51)
    bd: int = Field(ge=0, le=51)
    uhd: int = Field(ge=0, le=51)


# Encode choices (ADR 0010). `encode.py` maps each to ffmpeg arguments; the Settings
# page lists them in this order.
EncoderName = Literal["hevc_nvenc", "av1_nvenc", "hevc_qsv", "libx265"]
Speed = Literal["faster", "balanced", "slower", "slowest"]  # fastest to slowest
AudioChoice = Literal["all", "first_plus_stereo", "languages"]
SubtitleChoice = Literal["all", "languages", "none"]


class MaxResolutionConfig(_Section):
    """The tallest picture an Encode of each Disc Type keeps; "keep" = the Disc's own."""

    dvd: Literal["keep"] = "keep"
    bd: Literal["keep", "720p"] = "keep"
    uhd: Literal["keep", "1080p"] = "keep"


def _languages(value: str) -> str:
    parse_languages(value)
    return value


class EncodeConfig(_Section):
    encoder: EncoderName = "hevc_nvenc"
    speed: Speed = "slower"
    audio: AudioChoice = "languages"
    subtitles: SubtitleChoice = "languages"
    languages: Annotated[str, AfterValidator(_languages)] = "English"  # as typed
    cq: CqConfig
    max_resolution: MaxResolutionConfig = MaxResolutionConfig()

    @property
    def preferred_languages(self) -> tuple[str, ...]:
        """ISO 639-1 codes, most preferred first."""
        return parse_languages(self.languages)


class LibraryKind(StrEnum):
    """What a Library holds; each kind has one default Library."""

    FILMS = "films"
    TV = "tv"
    MUSIC = "music"

    @property
    def label(self) -> str:
        return _KINDS[self][0]

    @property
    def folder(self) -> str:
        """The kind's folder name, as Plex lays it out: its default Library's name and the
        first part of an archiver's logical path."""
        return _KINDS[self][1]

    def default_path(self) -> Path:
        """The kind's default Library folder when none are configured."""
        return Path.home().joinpath(*_KINDS[self][2])


# kind -> (label, folder name, default Library folder under the user's home)
_KINDS = {LibraryKind.FILMS: ("Films", "Movies", ("Videos", "Movies")),
          LibraryKind.TV: ("TV", "TV", ("Videos", "TV")),
          LibraryKind.MUSIC: ("Music", "Music", ("Music",))}


def _not_blank(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("This can't be empty")
    return value


def library_folder(value: str) -> str:
    """A Library's folder: a full path, wherever it is (ADR 0011)."""
    value = _not_blank(value)
    if not Path(value).is_absolute():
        raise ValueError(r"Enter the full folder path, like D:\Movies or \\nas\media\Movies")
    return value


class Library(_Section):
    """A named folder of the Archive for one kind of media, matching one Plex library."""

    name: Annotated[str, AfterValidator(_not_blank)]
    kind: LibraryKind
    path: Annotated[str, AfterValidator(library_folder)]
    plex: str = ""  # the Plex library's name; empty = whichever Plex library holds the folder
    default: bool = False


class Config(_Section):
    web: WebConfig = WebConfig()
    drive: DriveConfig = DriveConfig()
    cd: CdConfig = CdConfig()
    tools: ToolsConfig = ToolsConfig()
    paths: PathsConfig
    scratch: ScratchConfig = ScratchConfig()
    rip: RipConfig = RipConfig()
    tmdb: TmdbConfig = TmdbConfig()
    plex: PlexConfig = PlexConfig()
    discord: DiscordConfig = DiscordConfig()
    ntfy: NtfyConfig = NtfyConfig()
    webhook: WebhookConfig = WebhookConfig()
    encode: EncodeConfig
    logs: LogsConfig = LogsConfig()
    # Empty in the file = one default per kind under the user's home (`LibraryKind.default_path`).
    libraries: tuple[Library, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def _default_libraries(cls, data: Any) -> Any:
        if not isinstance(data, dict) or data.get("libraries"):
            return data
        return {**data, "libraries": [
            {"name": k.folder, "kind": k.value, "path": str(k.default_path()), "default": True}
            for k in LibraryKind]}

    @model_validator(mode="after")
    def _check_libraries(self) -> Config:
        names = [lib.name.casefold() for lib in self.libraries]
        for lib in self.libraries:
            if names.count(lib.name.casefold()) > 1:
                raise ValueError(f"Two Libraries are called {lib.name}; give each its own name")
        for kind in LibraryKind:
            defaults = [lib for lib in self.libraries if lib.kind == kind and lib.default]
            if not defaults:
                raise ValueError(f"{kind.label} has no default Library: "
                                 "mark one of them default = true")
            if len(defaults) > 1:
                raise ValueError(f"{kind.label} can only have one default Library, not "
                                 + " and ".join(lib.name for lib in defaults))
        return self



def library_for(libraries: Sequence[Library], kind: LibraryKind,
                picked: str | None = None) -> Library:
    """The Library a Job of `kind` files to: the one it picked if that still exists, else
    the kind's default (a removed pick falls back to it)."""
    ofkind = [lib for lib in libraries if lib.kind == kind]
    return (next((lib for lib in ofkind if picked and lib.name == picked), None)
            or next(lib for lib in ofkind if lib.default))


def secret_values(model: BaseModel) -> list[str]:
    """Every secret set in `model` (fields declared with `repr=False`), for masking output."""
    found: list[str] = []
    for name, field in type(model).model_fields.items():
        value = getattr(model, name)
        if isinstance(value, BaseModel):
            found += secret_values(value)
        elif not field.repr and isinstance(value, str) and value:
            found.append(value)
    return found


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
            ": ".join(filter(None, [".".join(map(str, err["loc"])),
                                    err["msg"].removeprefix("Value error, ")]))
            for err in e.errors()
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
    update: dict = {"paths": paths}
    if cfg.tools.dir:
        update["tools"] = cfg.tools.model_copy(update={"dir": str(base / cfg.tools.dir)})
    return cfg.model_copy(update=update)
