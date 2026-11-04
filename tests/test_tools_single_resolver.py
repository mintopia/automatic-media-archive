"""Every external tool is resolved through `ama.tools` (ADR 0006): no caller names an
executable path or searches PATH itself."""

import re
from pathlib import Path

SRC = Path(__file__).parent.parent / "src" / "ama"
FORBIDDEN = re.compile(
    r"(ffmpeg|ffprobe|cyanrip|makemkvcon)(64)?\.exe|shutil\.which|Program Files", re.IGNORECASE)


def test_only_the_resolver_knows_where_tools_live():
    offenders = [
        f"{p.relative_to(SRC)}:{n}: {line.strip()}"
        for p in SRC.rglob("*.py") if p.name != "tools.py"
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if FORBIDDEN.search(line)
    ]
    assert offenders == []
