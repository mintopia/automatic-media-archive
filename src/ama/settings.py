"""Editing `ama.toml` from the UI (ADR 0008): the file is the only settings source.

`SettingsFile.save` validates an edit through the same `Config` models startup uses,
then rewrites the file in place with tomlkit (comments and key order kept),
atomically, keeping one `.bak`. `Settings` compares the file with what this
process runs: keys in `LIVE_TABLES` are applied at once (from the UI or a hand
edit, which `run()` notices), the rest wait for a restart and are `pending()`.
Keys are dotted TOML paths, e.g. "web.port", "encode.cq.uhd".
"""

from __future__ import annotations

import asyncio
import copy
import logging
import os
import shutil
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any

import tomlkit
import tomlkit.exceptions
from pydantic import BaseModel, ValidationError
from pydantic.fields import FieldInfo

from ama.config import EDITED, Config, ConfigError, Kind, load_config

log = logging.getLogger(__name__)

# Tables whose new values running code picks up at once (`Services.apply_live`).
# Everything else is read once at startup. A table added here needs its consumer
# wired in `apply_live`.
LIVE_TABLES = frozenset({"cd", "encode", "plex", "tmdb", "discord", "ntfy", "libraries",
                         "logs"})


def is_live(key: str) -> bool:
    return key.split(".", 1)[0] in LIVE_TABLES


def keys(model: type[BaseModel] = Config, prefix: str = "") -> Iterator[str]:
    """Every setting's key, in model order."""
    for name, f in model.model_fields.items():
        if isinstance(f.annotation, type) and issubclass(f.annotation, BaseModel):
            yield from keys(f.annotation, f"{prefix}{name}.")
        else:
            yield f"{prefix}{name}"


def field_info(key: str) -> FieldInfo:
    model: type[BaseModel] = Config
    *tables, name = key.split(".")
    for t in tables:
        model = model.model_fields[t].annotation  # type: ignore[assignment]
    return model.model_fields[name]


def is_secret(key: str) -> bool:
    """Secrets are the fields declared with `repr=False` (config._secret)."""
    return not field_info(key).repr


def value_at(cfg: BaseModel, key: str) -> Any:
    v: Any = cfg
    for part in key.split("."):
        v = getattr(v, part)
    return v


def raw_at(data: Mapping[str, Any], key: str) -> Any:
    """The value as written in the file, or None when the file leaves it out."""
    v: Any = data
    for part in key.split("."):
        if not isinstance(v, Mapping) or part not in v:
            return None
        v = v[part]
    return v


class SettingsRejected(Exception):
    """An edit that doesn't validate. `errors` maps each submitted key to its fix;
    `general` holds problems elsewhere in the file. The file is unchanged."""

    def __init__(self, errors: dict[str, str], general: list[str]) -> None:
        super().__init__("; ".join([*errors.values(), *general]))
        self.errors = errors
        self.general = general


def _message(err: Mapping[str, Any]) -> str:
    ctx = err.get("ctx") or {}
    match err["type"]:
        case "int_parsing" | "int_from_float" | "int_type":
            return "Enter a whole number"
        case "float_parsing" | "float_type":
            return "Enter a number"
        case "greater_than":
            return f"Enter a number above {ctx['gt']}"
        case "greater_than_equal":
            return f"Enter {ctx['ge']} or more"
        case "less_than_equal":
            return f"Enter {ctx['le']} or less"
        case "less_than":
            return f"Enter a number below {ctx['lt']}"
        case "value_error":
            return str(ctx.get("error", err["msg"]))
        case "missing":
            return "This can't be empty"
    return str(err["msg"])


def _set(data: dict, key: str, value: Any) -> None:
    *tables, name = key.split(".")
    for t in tables:
        data = data.setdefault(t, {})
    data[name] = value


def _toml_value(value: Any, typed: str) -> Any:
    """What to write: numbers as TOML numbers (3, not 3.0), text exactly as typed;
    a Windows path as a literal string, like the example file."""
    if isinstance(value, bool):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, int | float):
        return value
    if "\\" in typed and "'" not in typed and "\n" not in typed:
        return tomlkit.string(typed, literal=True)
    return typed


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    bak = path.with_name(path.name + ".bak")
    bak_tmp = path.with_name(path.name + ".bak.tmp")
    shutil.copy2(path, bak_tmp)
    os.replace(bak_tmp, bak)
    os.replace(tmp, path)


# A Library's keys that the file can leave out, and their value then.
_LIBRARY_OPTIONAL: dict[str, Any] = {"plex": "", "default": False}


class SettingsFile:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _text(self) -> str:
        return self.path.read_text(encoding="utf-8", newline="")

    def values(self) -> tuple[dict[str, Any], Config]:
        """The file as written (raw) and validated, paths left as written. Raises ConfigError."""
        try:
            data = tomlkit.parse(self._text()).unwrap()
        except FileNotFoundError:
            raise ConfigError(f"No config file at {self.path}") from None
        except tomlkit.exceptions.ParseError as e:
            raise ConfigError(f"{self.path}: {e}") from None
        try:
            return data, Config.model_validate(data)
        except ValidationError as e:
            raise ConfigError("; ".join(f"{'.'.join(map(str, err['loc']))}: {_message(err)}"
                                        for err in e.errors())) from None

    def save(self, changes: Mapping[str, str]) -> list[str]:
        """Apply `{key: typed text}`; returns the keys whose value changed. Raises
        SettingsRejected (file untouched) if the result wouldn't load at startup."""
        doc = tomlkit.parse(self._text())
        data = doc.unwrap()
        candidate = copy.deepcopy(data)
        for key, typed in changes.items():
            _set(candidate, key, typed)
        edited = {k for k in changes if raw_at(candidate, k) != raw_at(data, k)}
        try:
            new = Config.model_validate(candidate, context={EDITED: edited})
        except ValidationError as e:
            errors: dict[str, str] = {}
            general: list[str] = []
            for err in e.errors():
                key = ".".join(map(str, err["loc"]))
                if key in changes:
                    errors.setdefault(key, _message(err))
                else:
                    general.append(f"{key}: {_message(err)}")
            raise SettingsRejected(errors, general) from None
        try:
            current: Config | None = Config.model_validate(data)
        except ValidationError:
            current = None
        changed = [k for k in changes
                   if current is None or value_at(new, k) != value_at(current, k)]
        for key in changed:
            *tables, name = key.split(".")
            table: Any = doc
            for t in tables:
                if t not in table:
                    table[t] = tomlkit.table()
                table = table[t]
            table[name] = _toml_value(value_at(new, key), changes[key])
        if changed:
            _write_atomic(self.path, doc.as_string())
        return changed

    # -- Libraries: `[[libraries]]` entries, each saved on its own ---------------------

    def save_library(self, kind: Kind, original: str | None, typed: Mapping[str, str]) -> None:
        """Add a `kind` Library (`original` None) or edit the one called `original`, from
        `{"name", "plex", "path"}`; leaving out "plex" keeps the one it has. Raises
        SettingsRejected keyed by those names."""
        doc, libraries = self._libraries()
        index = (len(libraries) if original is None
                 else next((i for i, lib in enumerate(libraries) if lib["name"] == original),
                           None))
        if index is None:
            raise SettingsRejected({}, [f"There's no Library called {original}"])
        kept = libraries[index]["plex"] if original is not None else ""
        fields = {k: str(typed.get(k, kept if k == "plex" else "")).strip()
                  for k in ("name", "plex", "path")}
        errors: dict[str, str] = {}
        for k in ("name", "path"):
            if not fields[k]:
                errors[k] = "This can't be empty"
        clash = next((lib["name"] for i, lib in enumerate(libraries)
                      if i != index and lib["name"].casefold() == fields["name"].casefold()),
                     None)
        if clash and fields["name"]:
            errors["name"] = f"There's already a Library called {clash}"
        share = Path(doc.unwrap().get("nas", {}).get("unc", ""))
        if fields["path"] and (Path(fields["path"]) == share
                               or not Path(fields["path"]).is_relative_to(share)):
            errors["path"] = f"Pick a folder inside the NAS share, {share}"
        if errors:
            raise SettingsRejected(errors, [])
        if original is None:
            libraries.append({"name": fields["name"], "kind": kind.value, "path": fields["path"],
                              "plex": fields["plex"], "default": False})
        else:
            libraries[index] = libraries[index] | fields
        self._write_libraries(doc, libraries)

    def remove_library(self, name: str) -> None:
        doc, libraries = self._libraries()
        index = next((i for i, lib in enumerate(libraries) if lib["name"] == name), None)
        if index is None:
            return  # already gone
        if libraries[index]["default"]:
            raise SettingsRejected({}, [f"{name} is a default Library, so it can't be removed: "
                                        "make another Library the default first"])
        del libraries[index]
        self._write_libraries(doc, libraries, removed=index)

    def make_default(self, name: str) -> None:
        doc, libraries = self._libraries()
        chosen = next((lib for lib in libraries if lib["name"] == name), None)
        if chosen is None:
            raise SettingsRejected({}, [f"There's no Library called {name}"])
        for lib in libraries:
            if lib["kind"] == chosen["kind"]:
                lib["default"] = lib is chosen
        self._write_libraries(doc, libraries)

    def _libraries(self) -> tuple[tomlkit.TOMLDocument, list[dict[str, Any]]]:
        """The file and its Libraries as plain values (the defaults when it lists none)."""
        _, cfg = self.values()
        doc = tomlkit.parse(self._text())
        return doc, [lib.model_dump(mode="json") for lib in cfg.libraries]

    def _write_libraries(self, doc: tomlkit.TOMLDocument, libraries: list[dict[str, Any]],
                         removed: int | None = None) -> None:
        """Validate `libraries` as the whole file would load, then change only the entries
        that differ (an entry left out of the file, `removed`, is deleted)."""
        candidate = doc.unwrap() | {"libraries": libraries}
        try:
            Config.model_validate(candidate)
        except ValidationError as e:
            raise SettingsRejected({}, [_message(err) for err in e.errors()]) from None
        if "libraries" not in doc:
            # The file relied on the defaults: write out the ones in use.
            doc.add(tomlkit.nl())
            doc["libraries"] = tomlkit.aot()
        aot = doc["libraries"]
        if removed is not None and removed < len(aot):
            del aot[removed]
        for i, want in enumerate(libraries):
            if i >= len(aot):
                aot.append(tomlkit.table())
            entry = aot[i]
            for key in ("name", "kind", "path", "plex", "default"):
                value = want[key]
                optional = key in _LIBRARY_OPTIONAL  # left out of the file when empty
                if entry.get(key, _LIBRARY_OPTIONAL.get(key)) == value:
                    continue
                if optional and not value:
                    del entry[key]
                else:
                    entry[key] = _toml_value(value, str(value))
        _write_atomic(self.path, doc.as_string())


class Settings:
    """The running config versus the file. `config` is what code should read now."""

    def __init__(self, path: Path | None, started: Config,
                 apply: Callable[[Config], None] = lambda cfg: None,
                 interval: float = 2.0) -> None:
        self.file = SettingsFile(Path(path).resolve()) if path else None
        self.started = started  # what restart-only keys run with until AMA restarts
        self.saved = started  # the file as last loaded (paths resolved)
        self.config = started
        self.problem: str | None = None  # why the file doesn't load right now
        self.interval = interval
        self._apply = apply
        self._stamp = self._stat()

    def _stat(self) -> tuple[int, int] | None:
        if self.file is None:
            return None
        try:
            st = self.file.path.stat()
        except OSError:
            return None
        return st.st_mtime_ns, st.st_size

    def refresh(self, force: bool = False) -> None:
        """Re-read the file if it changed; apply its live keys. Idempotent."""
        if self.file is None:
            return
        stamp = self._stat()
        if stamp == self._stamp and not force:
            return
        self._stamp = stamp
        try:
            new = load_config(self.file.path)
        except ConfigError as e:
            if self.problem != str(e):
                log.warning("settings: ama.toml doesn't load, keeping the running values: %s", e)
            self.problem = str(e)
            return
        self.problem = None
        self.saved = new
        self.config = self.started.model_copy(
            update={t: getattr(new, t) for t in LIVE_TABLES})
        self._apply(self.config)

    def pending(self) -> list[str]:
        """Saved keys that only take effect after a restart."""
        return [k for k in keys() if not is_live(k)
                and value_at(self.started, k) != value_at(self.saved, k)]

    def save(self, changes: Mapping[str, str]) -> list[str]:
        if self.file is None:
            raise SettingsRejected({}, ["AMA wasn't started from a config file"])
        changed = self.file.save(changes)
        self.refresh(force=True)
        return changed

    def _file(self) -> SettingsFile:
        if self.file is None:
            raise SettingsRejected({}, ["AMA wasn't started from a config file"])
        return self.file

    def save_library(self, kind: Kind, original: str | None, typed: Mapping[str, str]) -> None:
        self._file().save_library(kind, original, typed)
        self.refresh(force=True)

    def remove_library(self, name: str) -> None:
        self._file().remove_library(name)
        self.refresh(force=True)

    def make_default(self, name: str) -> None:
        self._file().make_default(name)
        self.refresh(force=True)

    async def run(self) -> None:
        """Notice hand edits: a hand edit and a UI edit are the same thing."""
        while True:
            await asyncio.sleep(self.interval)
            try:
                self.refresh()
            except Exception:  # noqa: BLE001 - never kill the loop
                log.exception("settings: couldn't re-read ama.toml")
