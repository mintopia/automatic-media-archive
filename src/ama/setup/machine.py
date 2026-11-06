"""This PC as Setup sees it: its optical drives, MakeMKV, and AMA's own tools (ADR 0006)
downloading in the background from the moment Setup opens (ADR 0016).

The downloads land where AMA looks for them after Setup (`Tools.provision` is idempotent),
so AMA starts with them in place. Nothing here blocks Setup except the Ready step, which
waits while a download is under way; a failed one doesn't block (AMA keeps retrying).
"""

from __future__ import annotations

import asyncio
import sys
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from ama.config import ToolsConfig
from ama.events import EventBus
from ama.tools import ToolFailed, Tools, ToolStatus


@dataclass(frozen=True)
class Download:
    label: str  # "ffmpeg 9.0.2"
    status: ToolStatus


@dataclass(frozen=True)
class Drive:
    device: str  # "D:"
    name: str  # what MakeMKV calls it ("" until MakeMKV has listed it)


def _optical_drives() -> tuple[str, ...]:
    if sys.platform != "win32":
        return ()
    from ama.drive import WindowsDriveProbe
    return WindowsDriveProbe().drives()


class Machine:
    def __init__(self, tools: Tools,
                 drives: Callable[[], Sequence[str]] = _optical_drives) -> None:
        self.tools = tools
        self._drives = drives
        self._lock = threading.Lock()
        self._provisioning = False

    @classmethod
    def this_pc(cls) -> Machine:
        return cls(Tools(ToolsConfig(), EventBus()))

    def start(self) -> None:
        """Download AMA's tools and check MakeMKV, in the background. Does nothing while a
        download is already under way, so it's also "try again"."""
        with self._lock:
            if self._provisioning:
                return
            self._provisioning = True
        threading.Thread(target=asyncio.run, args=(self._run(),), daemon=True,
                         name="setup-tools").start()

    async def _run(self) -> None:
        async def provision() -> None:
            try:
                await self.tools.provision()
            finally:
                self._provisioning = False
        await asyncio.gather(provision(), self.tools.check_makemkv())

    def downloads(self) -> list[Download]:
        """One per pinned download (a download's executables share its status)."""
        return [Download(pin.label, self.tools.status(pin.members[0].name))
                for pin in self.tools.pins]

    @property
    def busy(self) -> bool:
        """The downloads are under way (or being checked): Ready waits for them."""
        return self._provisioning

    @property
    def failed(self) -> list[Download]:
        return [d for d in self.downloads() if isinstance(d.status, ToolFailed)]

    @property
    def makemkv(self) -> ToolStatus:
        return self.tools.status("makemkvcon")

    def drives(self) -> list[Drive]:
        """The optical drives the OS reports now, the auto-detected one first."""
        try:
            found = self._drives()
        except OSError:
            found = ()
        return [Drive(d, self.tools.drive_names.get(d, "")) for d in found]
