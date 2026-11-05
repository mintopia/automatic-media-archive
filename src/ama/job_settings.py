"""Per-Job settings (#30): a Job's overrides of ama.toml, and each group's lock.

Until a group's Phase starts, the Job follows ama.toml for every value it hasn't
overridden, so a changed default reaches it. When the Phase starts the group locks:
its effective values (with the defaults of the moment) are stored on the Job, used
from then on, and further edits are refused (`Locked`). Rip locks when the Rip starts,
Encode when the Job's first Title Encode starts, Library and Identification when
filing starts.

Only settings that exist in ama.toml are here (the #29 review): a group with no
setting for a Job's Disc Type is left out of its page.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import get_args

from ama import encode
from ama.config import (AudioChoice, CdConfig, Config, EncodeConfig, LibraryKind,
                        MaxResolutionConfig, SubtitleChoice, library_for)
from ama.db import Database
from ama.drive import DiscType
from ama.jobs import JobRecord, JobStore
from ama.languages import name_of, parse_languages


class Group(StrEnum):
    RIP = "rip"
    IDENTIFICATION = "identification"
    ENCODE = "encode"
    LIBRARY = "library"

    @property
    def label(self) -> str:
        return self.value.capitalize()

    @property
    def phase(self) -> str:
        """The Phase whose start locks the group, as the lock line names it."""
        return {"rip": "Ripping", "encode": "Encoding"}.get(self.value, "Filed")

    @property
    def locked_line(self) -> str:
        p = self.phase
        return "Locked when Filed" if p == "Filed" else f"Locked at {p} start"

    @property
    def until(self) -> str:
        p = self.phase
        return "Can change until Filed." if p == "Filed" else f"Can change until {p} starts."


class Locked(Exception):
    """The group locked before this edit: it wasn't saved."""

    def __init__(self, group: Group, at: datetime) -> None:
        super().__init__(f"{group.label} locked at {at:%H:%M}")
        self.group = group
        self.at = at


@dataclass(frozen=True)
class Scope:
    """What a setting's choices and default depend on."""

    cfg: Config
    disc_type: DiscType
    kind: LibraryKind  # the Library kind the Job files to (as far as is known)


Choices = tuple[tuple[str, str], ...]  # (value, label)


@dataclass(frozen=True)
class Setting:
    key: str
    group: Group
    label: str
    default: Callable[[Scope], str]
    choices: Callable[[Scope], Choices] | None = None  # None: typed text, see `check`
    text: Callable[[str, Scope], str] = lambda v, s: v  # a value in words
    applies: Callable[[DiscType], bool] = lambda t: True
    check: Callable[[str], str] | None = None  # normalise typed text; raise ValueError
    note: str = ""  # under an override, before "default …"


def _video(t: DiscType) -> bool:
    return t != DiscType.CD


def _of_type(model: object, t: DiscType) -> object:
    return getattr(model, t.name.lower())


_NATIVE = {DiscType.DVD: "576p", DiscType.BD: "1080p", DiscType.UHD: "2160p"}


def _resolutions(t: DiscType) -> tuple[str, ...]:
    return get_args(MaxResolutionConfig.model_fields[t.name.lower()].annotation)


def _resolution_text(v: str, s: Scope) -> str:
    return _NATIVE[s.disc_type] if v == "keep" else v


_AUDIO: dict[AudioChoice, str] = {"all": "Copy all", "first_plus_stereo":
                                  "First track, plus a stereo copy",
                                  "languages": "Preferred languages"}
_SUBTITLES: dict[SubtitleChoice, str] = {"languages": "Preferred languages", "all": "All",
                                         "none": "None"}


def _quality(v: str) -> str:
    n = int(v)  # ValueError: not a number
    if not 0 <= n <= 51:
        raise ValueError("Quality runs from 0 to 51")
    return str(n)


def _quality_choices(s: Scope) -> Choices:
    return tuple((str(n), str(n)) for n in range(52))


def _languages(v: str) -> str:
    v = " ".join(v.split())
    parse_languages(v)  # ValueError names the word it didn't know
    return v


def _languages_text(v: str, s: Scope) -> str:
    return ", ".join(name_of(c) for c in parse_languages(v))


def _offset_text(v: str, s: Scope) -> str:
    return f"{int(v):+d} samples"


SETTINGS: tuple[Setting, ...] = (
    Setting("encode.quality", Group.ENCODE, "Quality",
            lambda s: str(encode.cq_for(s.cfg.encode.cq, s.disc_type)), _quality_choices,
            applies=_video, check=_quality, note="Lower keeps more detail"),
    Setting("encode.encoder", Group.ENCODE, "Encoder", lambda s: s.cfg.encode.encoder,
            lambda s: tuple((e, p.label) for e, p in encode.ENCODERS.items()),
            lambda v, s: encode.ENCODERS[v].label, _video),  # type: ignore[index]
    Setting("encode.max_resolution", Group.ENCODE, "Max resolution",
            lambda s: str(_of_type(s.cfg.encode.max_resolution, s.disc_type)),
            lambda s: tuple((v, _resolution_text(v, s)) for v in _resolutions(s.disc_type)),
            _resolution_text, lambda t: _video(t) and len(_resolutions(t)) > 1),
    Setting("encode.speed", Group.ENCODE, "Speed", lambda s: s.cfg.encode.speed,
            lambda s: tuple((v, encode.SPEED_LABELS[v]) for v in encode.SPEEDS),
            lambda v, s: encode.SPEED_LABELS[v], _video),  # type: ignore[index]
    Setting("encode.audio", Group.ENCODE, "Audio", lambda s: s.cfg.encode.audio,
            lambda s: tuple(_AUDIO.items()), lambda v, s: _AUDIO[v], _video),  # type: ignore[index]
    Setting("encode.subtitles", Group.ENCODE, "Subtitles", lambda s: s.cfg.encode.subtitles,
            lambda s: tuple(_SUBTITLES.items()), lambda v, s: _SUBTITLES[v],  # type: ignore[index]
            _video),
    Setting("encode.languages", Group.ENCODE, "Preferred languages",
            lambda s: s.cfg.encode.languages, None, _languages_text, _video, _languages),
    Setting("library", Group.LIBRARY, "Files to",
            lambda s: library_for(s.cfg.libraries, s.kind).name,
            lambda s: tuple((lib.name, lib.name) for lib in
                            sorted((lib for lib in s.cfg.libraries if lib.kind == s.kind),
                                   key=lambda lib: not lib.default))),
    Setting("cd.offset", Group.RIP, "Drive read offset", lambda s: str(s.cfg.cd.offset),
            text=_offset_text, applies=lambda t: t == DiscType.CD, check=lambda v: str(int(v))),
    Setting("cd.retries", Group.RIP, "Re-reads before an error",
            lambda s: str(s.cfg.cd.retries), applies=lambda t: t == DiscType.CD,
            check=lambda v: str(max(1, int(v)))),
)
_BY_KEY = {s.key: s for s in SETTINGS}


def setting(key: str) -> Setting | None:
    return _BY_KEY.get(key)


def settings_of(disc_type: DiscType, group: Group | None = None) -> list[Setting]:
    return [s for s in SETTINGS if s.applies(disc_type) and group in (None, s.group)]


@dataclass(frozen=True)
class Value:
    """One setting's value for a Job: effective, the default it overrides (equal if not)."""

    setting: Setting
    value: str
    default: str
    text: str
    default_text: str

    @property
    def overridden(self) -> bool:
        return self.value != self.default


@dataclass(frozen=True)
class GroupState:
    group: Group
    values: list[Value]
    locked_at: datetime | None

    @property
    def locked(self) -> bool:
        return self.locked_at is not None


class JobSettings:
    """`services.job_settings`. Thread-safe: an edit and a lock never interleave."""

    def __init__(self, db: Database, jobs: JobStore, config: Callable[[], Config],
                 kind_of: Callable[[JobRecord], LibraryKind]) -> None:
        self._db = db
        self._jobs = jobs
        self._config = config  # the running settings (ama.toml as last applied)
        self._kind_of = kind_of
        self._lock = threading.Lock()

    # -- reading -------------------------------------------------------------

    def scope(self, job: JobRecord, kind: LibraryKind | None = None) -> Scope:
        return Scope(self._config(), job.disc_type, kind or self._kind_of(job))

    def _overrides(self, job_id: int) -> dict[str, str]:
        return dict(self._db.execute("SELECT key, value FROM job_overrides WHERE job_id = ?",
                                     (job_id,)).fetchall())

    def _stored(self, job_id: int, group: Group) -> tuple[datetime, dict] | None:
        row = self._db.execute("SELECT locked_at, settings FROM job_locks "
                               "WHERE job_id = ? AND grp = ?", (job_id, group.value)).fetchone()
        return (datetime.fromisoformat(row[0]), json.loads(row[1])) if row else None

    def locked_at(self, job_id: int, group: Group) -> datetime | None:
        stored = self._stored(job_id, group)
        return stored[0] if stored else None

    def _open_values(self, job: JobRecord, group: Group, scope: Scope) -> list[Value]:
        overrides = self._overrides(job.id)
        out = []
        for s in settings_of(job.disc_type, group):
            default = s.default(scope)
            value = overrides.get(s.key, default)
            if s.choices and value not in dict(s.choices(scope)):
                value = default  # e.g. a picked Library since removed, or of another kind
            out.append(Value(s, value, default, s.text(value, scope), s.text(default, scope)))
        return out

    def group(self, job: JobRecord, group: Group) -> GroupState:
        scope = self.scope(job)
        stored = self._stored(job.id, group)
        if stored is None:
            return GroupState(group, self._open_values(job, group, scope), None)
        at, saved = stored
        values = []
        for s in settings_of(job.disc_type, group):
            if s.key in saved:
                value, default = saved[s.key]
                values.append(Value(s, value, default, s.text(value, scope),
                                    s.text(default, scope)))
        return GroupState(group, values, at)

    def groups(self, job: JobRecord) -> list[GroupState]:
        """Every group with a setting for this Job, in the panel's order."""
        order = ([Group.IDENTIFICATION, Group.LIBRARY, Group.RIP] if job.disc_type == DiscType.CD
                 else [Group.ENCODE, Group.LIBRARY, Group.IDENTIFICATION, Group.RIP])
        return [g for g in (self.group(job, grp) for grp in order) if g.values]

    # -- editing -------------------------------------------------------------

    def set(self, job_id: int, key: str, value: str) -> None:
        """Override `key` for this Job (the default value = no override). Raises Locked,
        ValueError (not a value this Job can take, or no such setting for it)."""
        job = self._job(job_id)
        setting = _BY_KEY.get(key)
        if setting is None or not setting.applies(job.disc_type):
            raise ValueError(f"This Job has no setting {key}")
        scope = self.scope(job)
        if setting.check:
            value = setting.check(value)
        if setting.choices and value not in dict(setting.choices(scope)):
            raise ValueError(f"{value} isn't one of the choices for {setting.label}")
        with self._lock:
            self._refuse_if_locked(job_id, setting.group)
            if value == setting.default(scope):
                self._delete(job_id, key)
            else:
                self._db.execute(
                    "INSERT INTO job_overrides (job_id, key, value) VALUES (?, ?, ?) "
                    "ON CONFLICT(job_id, key) DO UPDATE SET value = excluded.value",
                    (job_id, key, value))

    def reset(self, job_id: int, key: str) -> None:
        """Follow ama.toml again for `key`. Raises Locked."""
        setting = _BY_KEY.get(key)
        if setting is None:
            raise ValueError(f"No setting {key}")
        with self._lock:
            self._refuse_if_locked(job_id, setting.group)
            self._delete(job_id, key)

    def _delete(self, job_id: int, key: str) -> None:
        self._db.execute("DELETE FROM job_overrides WHERE job_id = ? AND key = ?", (job_id, key))

    def _refuse_if_locked(self, job_id: int, group: Group) -> None:
        at = self.locked_at(job_id, group)
        if at is not None:
            raise Locked(group, at)

    def _job(self, job_id: int) -> JobRecord:
        job = self._jobs.get(job_id)
        if job is None:
            raise ValueError(f"No Job {job_id}")
        return job

    # -- locking at Phase start -----------------------------------------------

    def lock(self, job: JobRecord, group: Group, kind: LibraryKind | None = None) -> dict[str, str]:
        """Lock `group` now if it isn't yet (idempotent); its values, {key: value}."""
        with self._lock:
            stored = self._stored(job.id, group)
            if stored is None:
                values = self._open_values(job, group, self.scope(job, kind))
                at = datetime.now()
                self._db.execute(
                    "INSERT INTO job_locks (job_id, grp, locked_at, settings) "
                    "VALUES (?, ?, ?, ?)",
                    (job.id, group.value, at.isoformat(timespec="seconds"),
                     json.dumps({v.setting.key: [v.value, v.default] for v in values})))
                if values:
                    self._jobs.log(job.id, f"{group.label} settings locked: " + ", ".join(
                        f"{v.setting.label} {v.text}"
                        + (" (changed for this Job)" if v.overridden else "") for v in values))
                return {v.setting.key: v.value for v in values}
            return {k: v for k, (v, _default) in stored[1].items()}

    def encode_config(self, job: JobRecord) -> EncodeConfig:
        """The Job's Encode settings; locks the Encode group (its Encode is starting)."""
        v = self.lock(job, Group.ENCODE)
        enc = self._config().encode
        t = job.disc_type.name.lower()
        update: dict = {k.removeprefix("encode."): v[k] for k in
                        ("encode.encoder", "encode.speed", "encode.audio", "encode.subtitles",
                         "encode.languages") if k in v}
        if "encode.quality" in v:
            update["cq"] = enc.cq.model_copy(update={t: int(v["encode.quality"])})
        if "encode.max_resolution" in v:
            update["max_resolution"] = enc.max_resolution.model_copy(
                update={t: v["encode.max_resolution"]})
        return enc.model_copy(update=update)

    def library(self, job: JobRecord, kind: LibraryKind) -> str:
        """The Library a Job of `kind` files to; locks Library and Identification (filing
        is starting)."""
        self.lock(job, Group.IDENTIFICATION, kind)
        return self.lock(job, Group.LIBRARY, kind).get(
            "library", library_for(self._config().libraries, kind).name)

    def rip_config(self, job: JobRecord) -> CdConfig:
        """A CD Job's Rip settings; locks the Rip group (its Rip is starting)."""
        v = self.lock(job, Group.RIP)
        return self._config().cd.model_copy(update={
            "offset": int(v.get("cd.offset", self._config().cd.offset)),
            "retries": int(v.get("cd.retries", self._config().cd.retries))})
