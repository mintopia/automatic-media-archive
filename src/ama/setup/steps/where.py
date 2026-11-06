"""Where things go: one Library per kind, prefilled with the defaults; Scratch under
Advanced. Each folder must be one AMA can write to (it needn't exist yet)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from ama.config import LibraryKind, library_folder
from ama.setup import Draft, Step, Values

SCRATCH = "scratch"
FIELDS = {LibraryKind.FILMS: "films", LibraryKind.TV: "tv", LibraryKind.MUSIC: "music"}


def _defaults(config: Path) -> dict[str, str]:
    return {**{name: str(kind.default_path()) for kind, name in FIELDS.items()},
            SCRATCH: str(config.parent / "Scratch")}


def unwritable(folder: str) -> str | None:
    """Why AMA couldn't write to `folder` (created when first needed), or None."""
    try:
        library_folder(folder)
    except ValueError as e:
        return str(e)
    path = Path(folder)
    existing = next((p for p in (path, *path.parents) if p.exists()), None)
    if existing is None:
        return "AMA can't find this drive or share"
    if not existing.is_dir():
        return f"AMA can't write here: {existing} is a file, not a folder"
    try:
        with tempfile.TemporaryFile(dir=existing):
            pass
    except OSError:
        return f"AMA can't write to {existing}: choose a folder you can save files in"
    return None


def _check(values: Values) -> dict[str, str]:
    return {name: problem for name in (*FIELDS.values(), SCRATCH)
            if (problem := unwritable(values.get(name, "")))}


def _settings(values: Values) -> Draft:
    return Draft(changes={"paths.scratch": values[SCRATCH]},
                 libraries=[{"name": kind.folder, "kind": kind.value, "path": values[name],
                             "default": True} for kind, name in FIELDS.items()])


def _summary(values: Values) -> list[tuple[str, str]]:
    return [*((kind.label, values[name]) for kind, name in FIELDS.items()),
            ("Scratch", values[SCRATCH])]


STEP = Step(slug="where", title="Where things go", order=30, template="setup/where.html",
            defaults=_defaults, check=_check, settings=_settings, summary=_summary)
