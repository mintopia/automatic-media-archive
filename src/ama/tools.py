"""External programs: the one resolver every caller gets executables from (ADR 0006).

`Tools.path(name)` returns the executable to run for "ffmpeg", "ffprobe",
"cyanrip" or "makemkvcon", or raises `ToolUnavailable` while that tool isn't
usable. A missing tool blocks only the work that needs it.

- ffmpeg/ffprobe and cyanrip are AMA's: pinned portable builds (`PINS`), downloaded
  into a per-user tools directory, verified by SHA-256 and unpacked. `provision()`
  is idempotent: a present tool whose hash matches is left alone, a missing or
  corrupt one is fetched again. Bumping a version means changing its pin.
- MakeMKV is the user's: AMA never installs or registers it. `check_makemkv()`
  checks it is present, runs (a too-old build says MSG 5021) and is registered,
  and `path("makemkvcon")` raises until all three pass.
- A `[tools]` config path for a tool is used as-is: no download, no hash check.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import shutil
import subprocess
import time
import urllib.request
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ama.config import ToolsConfig
from ama.events import EventBus, Topic
from ama.proc import Runner, run

log = logging.getLogger(__name__)

ToolName = Literal["ffmpeg", "ffprobe", "cyanrip", "makemkvcon"]
TOOL_NAMES: tuple[ToolName, ...] = ("ffmpeg", "ffprobe", "cyanrip", "makemkvcon")
ToolLookup = Callable[[str], Path]  # `Tools.path`, for callers that want just the lookup

# What each tool is for, in the words the UI uses.
NEEDED_FOR: dict[str, str] = {
    "ffmpeg": "Encodes", "ffprobe": "Encodes", "cyanrip": "CD Rips",
    "makemkvcon": "DVD and Blu-ray Rips",
}


@dataclass(frozen=True)
class Member:
    """One executable AMA takes from a pinned download (`archive_path` None = the download is it)."""

    name: ToolName
    archive_path: str | None
    sha256: str


@dataclass(frozen=True)
class Pin:
    key: str
    version: str
    url: str
    sha256: str  # of the download itself
    members: tuple[Member, ...]

    @property
    def label(self) -> str:
        return f"{self.key} {self.version}"


PINS: tuple[Pin, ...] = (
    # Gyan's release builds (linked from ffmpeg.org), GitHub mirror: static, NVENC included.
    # "full" rather than "essentials" for libvmaf/zscale (CQ calibration, HDR).
    Pin(key="ffmpeg", version="9.0.2",
        url="https://github.com/GyanD/codexffmpeg/releases/download/9.0.2/ffmpeg-9.0.2-full_build.zip",
        sha256="759d0a9831c436a0eb331ad36f236c06cb04aaa0005da46571f0e9d3d9206f6b",
        members=(
            Member("ffmpeg", "ffmpeg-9.0.2-full_build/bin/ffmpeg.exe",
                   "589e50b766d251afdf181dd664d40bd94407e200b019989fd7468c7d118a28d0"),
            Member("ffprobe", "ffmpeg-9.0.2-full_build/bin/ffprobe.exe",
                   "02264dfa4f56baaa31e443ece8aa16d397f6b008200e7fd184d22b9009e75fd3"),
        )),
    # AMA's own build of upstream commit 648b1ddd (0.9.4-rc3), which fixes 0.9.3.1's
    # AccurateRip and -D bugs; built by tools/cyanrip/build.ps1, hosted in this repo's
    # Forgejo generic package registry (ADR 0007). Public download, no token needed.
    Pin(key="cyanrip", version="0.9.4-rc3-g648b1dd",
        url=("https://git.mintopia.net/api/packages/mintopia/generic/cyanrip/"
             "0.9.4-rc3-g648b1dd/cyanrip-0.9.4-rc3-g648b1dd-win64.zip"),
        sha256="0b936259c0ecdf628e8446f42c778cf920e65de8556ccdaa0486c7b9df929d1d",
        members=(Member("cyanrip", "cyanrip.exe",
                        "851d72c61df34a3a6af5fc44aa1711582ec33bb22e198560bb8d52c3a089a94a"),)),
)

MAKEMKV_DOWNLOAD = "https://www.makemkv.com/download/"
MAKEMKV_BETA_KEY = "https://forum.makemkv.com/forum/viewtopic.php?t=1053"


def default_makemkv_candidates() -> tuple[Path, ...]:
    dirs = [os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
            os.environ.get("ProgramFiles", r"C:\Program Files")]
    return tuple(dict.fromkeys(Path(d) / "MakeMKV" / "makemkvcon64.exe" for d in dirs))


def default_tools_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "ama" / "tools"


# --- statuses ---------------------------------------------------------------

@dataclass(frozen=True)
class ToolReady:
    path: Path
    source: Literal["managed", "config", "installed"]
    version: str = ""


@dataclass(frozen=True)
class ToolPending:
    """Not checked yet (startup)."""


@dataclass(frozen=True)
class ToolDownloading:
    label: str
    done: int
    total: int | None


@dataclass(frozen=True)
class ToolFailed:
    label: str
    detail: str


@dataclass(frozen=True)
class ToolNotFound:
    """`[tools] <name>` in ama.toml names a file that isn't there."""

    name: str
    path: Path


@dataclass(frozen=True)
class MakemkvMissing:
    searched: tuple[str, ...]


@dataclass(frozen=True)
class MakemkvTooOld:
    version: str


@dataclass(frozen=True)
class MakemkvUnregistered:
    version: str


@dataclass(frozen=True)
class MakemkvKeyRejected:
    """MSG 5052/5055: the evaluation period is over, or the key entered isn't valid."""

    version: str


@dataclass(frozen=True)
class MakemkvBroken:
    detail: str


ManagedStatus = ToolReady | ToolPending | ToolDownloading | ToolFailed | ToolNotFound
MakemkvStatus = (ToolReady | ToolPending | MakemkvMissing | MakemkvTooOld | MakemkvUnregistered
                 | MakemkvKeyRejected | MakemkvBroken)
ToolStatus = ManagedStatus | MakemkvStatus


def makemkv_headline(status: ToolStatus) -> str:
    """One sentence saying what's wrong with MakeMKV (the `/makemkv` page has the fix)."""
    match status:
        case MakemkvMissing():
            return "Can't find MakeMKV on this PC."
        case MakemkvTooOld(version=v):
            return f"MakeMKV v{v} is too old to run."
        case MakemkvUnregistered():
            return "MakeMKV isn't registered."
        case MakemkvKeyRejected():
            return "MakeMKV says its licence key isn't valid."
        case MakemkvBroken():
            return "MakeMKV didn't run properly."
        case ToolReady():
            return "MakeMKV is ready."
        case _:
            return "MakeMKV hasn't been checked yet."


class ToolUnavailable(Exception):
    def __init__(self, name: str, status: ToolStatus) -> None:
        super().__init__(f"{name} isn't available: {status}")
        self.name = name
        self.status = status


# --- adapters ---------------------------------------------------------------

Fetch = Callable[[str, Path, Callable[[int, int | None], None]], None]


def download(url: str, dest: Path, progress: Callable[[int, int | None], None]) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "automatic-media-archive"})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0) or None
        done = 0
        while chunk := r.read(1 << 20):
            f.write(chunk)
            done += len(chunk)
            progress(done, total)


def read_makemkv_key() -> str:
    """The MakeMKV registration key of the current Windows user ("" if none)."""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\MakeMKV") as k:
            value, _ = winreg.QueryValueEx(k, "app_Key")
    except (OSError, ImportError):
        return ""
    return str(value or "")


def _sha256(path: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while chunk := f.read(1 << 20):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


class _ProvisionError(Exception):
    pass


_MAKEMKV_LICENCE_TOO_OLD = 5021
_MAKEMKV_LICENCE_EXPIRED = {5052, 5055}
_MSG = re.compile(r"^MSG:(\d+),")
_BANNER = re.compile(r"MakeMKV v(\d[\w.]*)")


class Tools:
    PROGRESS_PUBLISH_SECONDS = 0.5

    def __init__(
        self,
        cfg: ToolsConfig,
        bus: EventBus,
        runner: Runner = run,
        fetch: Fetch = download,
        read_key: Callable[[], str] = read_makemkv_key,
        pins: Sequence[Pin] = PINS,
        makemkv_candidates: Sequence[Path] | None = None,
        retry_seconds: float = 60.0,
    ) -> None:
        self.cfg = cfg
        self.bus = bus
        self.dir = Path(cfg.dir) if cfg.dir else default_tools_dir()
        self.pins = tuple(pins)
        self.retry_seconds = retry_seconds
        self._runner = runner
        self._fetch = fetch
        self._read_key = read_key
        self._makemkv_candidates = (default_makemkv_candidates() if makemkv_candidates is None
                                    else tuple(makemkv_candidates))
        self._status: dict[str, ToolStatus] = {n: ToolPending() for n in TOOL_NAMES}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._last_progress = 0.0

    # --- the resolver ---

    def path(self, name: str) -> Path:
        status = self.status(name)
        if isinstance(status, ToolReady):
            return status.path
        raise ToolUnavailable(name, status)

    def status(self, name: str) -> ToolStatus:
        status = self._status[name]  # KeyError: not a tool AMA knows
        override = self._override(name) if name != "makemkvcon" else None
        if override is None:
            return status
        # Looked at every time, so fixing the file (or the setting) needs no restart.
        return ToolReady(override, "config") if override.is_file() else ToolNotFound(name, override)

    def _override(self, name: str) -> Path | None:
        value = getattr(self.cfg, name)
        return Path(value) if value else None

    # --- lifecycle ---

    async def run(self) -> None:
        """Startup: check MakeMKV while provisioning, retrying failed downloads (and looking
        again for overrides that aren't there) until all are in."""
        await asyncio.gather(self.check_makemkv(), self._provision_until_ready())

    async def _provision_until_ready(self) -> None:
        while True:
            await self.provision()
            if not any(isinstance(self.status(n), ToolFailed | ToolNotFound)
                       for n in TOOL_NAMES):
                return
            await asyncio.sleep(self.retry_seconds)

    async def provision(self) -> None:
        """One idempotent pass over every pin. Failures become `ToolFailed`; nothing raises."""
        self._loop = asyncio.get_running_loop()
        for pin in self.pins:
            await asyncio.to_thread(self._provision_pin, pin)
            self.bus.publish(Topic.TOOLS)

    def _set(self, names: Sequence[str], status: ToolStatus, progress: bool = False) -> None:
        for n in names:
            self._status[n] = status
        now = time.monotonic()
        if progress and now - self._last_progress < self.PROGRESS_PUBLISH_SECONDS:
            return
        self._last_progress = now
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self.bus.publish, Topic.TOOLS)

    def _provision_pin(self, pin: Pin) -> None:
        wanted = [m for m in pin.members if self._override(m.name) is None]
        if not wanted:
            return
        names = [m.name for m in wanted]
        folder = self.dir / f"{pin.key}-{pin.version}"
        if all(_sha256(folder / f"{m.name}.exe") == m.sha256 for m in wanted):
            self._ready(pin, wanted, folder)
            return
        staging = self.dir / ".download"
        part = staging / f"{pin.key}-{pin.version}.part"
        try:
            staging.mkdir(parents=True, exist_ok=True)
            folder.mkdir(parents=True, exist_ok=True)
            part.unlink(missing_ok=True)
            log.info("downloading %s from %s", pin.label, pin.url)
            self._set(names, ToolDownloading(pin.label, 0, None))
            self._fetch(pin.url, part, lambda done, total: self._set(
                names, ToolDownloading(pin.label, done, total), progress=True))
            got = _sha256(part)
            if got != pin.sha256:
                raise _ProvisionError(
                    f"the download failed its SHA-256 check (got {got}, expected {pin.sha256})")
            for m in wanted:
                self._install(pin, m, part, folder)
        except Exception as e:  # noqa: BLE001 - any failure is reported and retried
            log.warning("provisioning %s failed: %s", pin.label, e)
            self._set(names, ToolFailed(pin.label, str(e) or type(e).__name__))
            return
        finally:
            part.unlink(missing_ok=True)
        log.info("%s ready in %s", pin.label, folder)
        self._ready(pin, wanted, folder)

    def _ready(self, pin: Pin, members: Sequence[Member], folder: Path) -> None:
        for m in members:
            self._status[m.name] = ToolReady(folder / f"{m.name}.exe", "managed", pin.version)

    @staticmethod
    def _install(pin: Pin, m: Member, part: Path, folder: Path) -> None:
        dest = folder / f"{m.name}.exe"
        new = folder / f"{m.name}.exe.new"
        if m.archive_path is None:
            shutil.copyfile(part, new)
        else:
            with zipfile.ZipFile(part) as z, z.open(m.archive_path) as src, open(new, "wb") as out:
                shutil.copyfileobj(src, out, 1 << 20)
        if _sha256(new) != m.sha256:
            new.unlink(missing_ok=True)
            raise _ProvisionError(f"{m.name}.exe in the download failed its SHA-256 check")
        os.replace(new, dest)

    # --- MakeMKV preflight ---

    async def watch_makemkv(self) -> None:
        """Background task: while MakeMKV isn't usable, check again every `retry_seconds`, so
        its banner goes once it's installed or registered (no button press needed)."""
        while True:
            await asyncio.sleep(self.retry_seconds)
            if not isinstance(self._status["makemkvcon"], ToolReady | ToolPending):
                await self.check_makemkv()

    async def check_makemkv(self) -> MakemkvStatus:
        status = await asyncio.to_thread(self._preflight)
        if status != self._status["makemkvcon"]:
            log.info("makemkv: %s", status)
        self._status["makemkvcon"] = status
        self.bus.publish(Topic.TOOLS)
        return status

    def _preflight(self) -> MakemkvStatus:
        override = self._override("makemkvcon")
        candidates = (override,) if override else self._makemkv_candidates
        exe = next((p for p in candidates if p.is_file()), None)
        if exe is None:
            return MakemkvMissing(tuple(str(p) for p in candidates))
        try:
            result = self._runner([str(exe), "-r", "--cache=1", "info", "disc:9999"])
        except subprocess.TimeoutExpired as e:
            return MakemkvBroken(
                f"{exe} started but didn't finish within {e.timeout:.0f} seconds. If the MakeMKV "
                "window is open, it may be showing a message: answer it or close MakeMKV.")
        except (OSError, subprocess.SubprocessError) as e:
            return MakemkvBroken(f"{exe} wouldn't start: {e}")
        lines = [ln.strip() for ln in result.output.splitlines() if ln.strip()]
        codes = {int(m.group(1)) for ln in lines if (m := _MSG.match(ln))}
        banner = next((m.group(1) for ln in lines if (m := _BANNER.search(ln))), None)
        version = banner or "?"
        if _MAKEMKV_LICENCE_TOO_OLD in codes:
            return MakemkvTooOld(version)
        if codes & _MAKEMKV_LICENCE_EXPIRED:
            return MakemkvKeyRejected(version)
        if banner is None:
            said = lines[-1] if lines else f"no output, exit code {result.returncode}"
            return MakemkvBroken(f"{exe} didn't run as expected: {said}")
        if not self._read_key().strip():
            return MakemkvUnregistered(version)
        return ToolReady(exe, "config" if override else "installed", version)
