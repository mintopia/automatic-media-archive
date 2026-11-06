"""`ama remove-data`: the uninstaller's "also remove settings and history" (ADR 0017).

Deletes the data folder (%LOCALAPPDATA%\\AMA: settings, database, logs, tools) but
never a Library: a Library folder inside it is kept, and if the data folder is
inside a Library nothing is removed. Settings that can't be read mean the Libraries
are unknown, so nothing is removed either. Running it again changes nothing more.
"""

from __future__ import annotations

import os
import shutil
import tomllib
from pathlib import Path


class Refused(Exception):
    """Nothing was removed; the message says why."""


def _key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(path))


def _inside(path: Path, folder: Path) -> bool:
    """`path` is `folder` or somewhere under it."""
    p, f = _key(path), _key(folder)
    return p == f or p.startswith(f.rstrip(os.sep) + os.sep)


def library_folders(config: Path) -> list[Path]:
    """The Library folders the settings file lists; none when there is no file."""
    try:
        data = tomllib.loads(config.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        raise Refused(f"couldn't read {config} to find your Libraries ({e}), "
                      "so nothing was removed") from None
    entries = data.get("libraries", [])
    if not isinstance(entries, list):
        entries = []
    return [Path(e["path"]) for e in entries
            if isinstance(e, dict) and isinstance(e.get("path"), str) and e["path"].strip()]


def remove_data(data: Path, libraries: list[Path]) -> None:
    """Delete `data`, keeping every Library folder inside it (and the folders leading
    to one); raise Refused, removing nothing, when `data` is inside a Library."""
    for library in libraries:
        if _inside(data, library):
            raise Refused(f"{data} is inside the Library {library}, so nothing was removed")
    if not data.exists():
        return
    _remove_except(data, [lib for lib in libraries if _inside(lib, data)])


def _remove_except(folder: Path, keep: list[Path]) -> None:
    for entry in folder.iterdir():
        if any(_key(entry) == _key(lib) for lib in keep):
            continue
        if any(_inside(lib, entry) for lib in keep):
            _remove_except(entry, keep)
        elif entry.is_symlink() or entry.is_junction():  # the link only, never its target
            entry.unlink() if entry.is_symlink() else entry.rmdir()
        elif entry.is_dir():
            shutil.rmtree(entry)
        else:
            entry.unlink()
    if not any(folder.iterdir()):
        folder.rmdir()
