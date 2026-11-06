"""The drive AMA rips from (the auto-detected one, or another the user picks), and whether
MakeMKV is found and registered. MakeMKV never holds Setup up: CDs work without it."""

from __future__ import annotations

import re
from pathlib import Path

from ama.setup import Draft, Step, Values

DRIVE = "drive"
_LETTER = re.compile(r"[A-Z]:")


def _defaults(config: Path) -> dict[str, str]:
    return {DRIVE: ""}  # none chosen: AMA uses the first drive it finds


def _check(values: Values) -> dict[str, str]:
    value = values.get(DRIVE, "")
    if value and not _LETTER.fullmatch(value):
        return {DRIVE: "Choose a drive from the list"}
    return {}


def _settings(values: Values) -> Draft:
    value = values.get(DRIVE, "")
    return Draft(changes={"drive.letter": value} if value else {})


def _summary(values: Values) -> list[tuple[str, str]]:
    return [("Drive", values.get(DRIVE) or "The first one AMA finds")]


STEP = Step(slug="drive", title="Drive and MakeMKV", order=20, template="setup/drive.html",
            fields=(DRIVE,), defaults=_defaults, check=_check, settings=_settings, summary=_summary)
