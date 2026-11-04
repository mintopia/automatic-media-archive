"""Where external tools live: the one lookup every caller resolves executables through.

ADR 0006: AMA will provision its own pinned portable tools (ticket #18), with a
config override per tool. Until that lands, each path comes from `[tools]` in
the config; an empty `cyanrip` means the bare name (found on PATH by Windows).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Literal

from ama.config import ToolsConfig

ToolName = Literal["cyanrip", "makemkvcon"]
ToolLookup = Callable[[ToolName], Path]


def lookup(cfg: ToolsConfig) -> ToolLookup:
    def path(name: ToolName) -> Path:
        match name:
            case "cyanrip":
                return Path(cfg.cyanrip) if cfg.cyanrip else Path("cyanrip")
            case "makemkvcon":
                return cfg.makemkvcon

    return path
