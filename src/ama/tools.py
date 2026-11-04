"""Where external tools live: the one lookup every caller resolves executables through.

ADR 0006: AMA will provision its own pinned portable tools (ticket #18), with a
config override per tool. Until that lands, a tool is its `[tools]` config
value, or its bare name (found on PATH by Windows) when that is empty.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ama.config import ToolsConfig

ToolLookup = Callable[[str], Path]


def lookup(cfg: ToolsConfig) -> ToolLookup:
    def path(name: str) -> Path:
        override = getattr(cfg, name, "")
        return Path(override) if override else Path(name)

    return path
