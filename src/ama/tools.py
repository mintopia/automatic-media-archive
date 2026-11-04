"""Where the external programs live. Every caller resolves executables here.

For now each path comes straight from `[tools]` in the config; ticket #18
replaces this with provisioned portable tools and a MakeMKV preflight (ADR-0006).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from ama.config import ToolsConfig

ToolName = Literal["makemkvcon"]


class Tools:
    def __init__(self, cfg: ToolsConfig) -> None:
        self._cfg = cfg

    def path(self, name: ToolName) -> Path:
        match name:
            case "makemkvcon":
                return self._cfg.makemkvcon
