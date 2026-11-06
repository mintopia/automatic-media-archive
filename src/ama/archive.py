"""Filing to the Archive: putting finished files into a Library's folder.

Each file is copied under a temporary name Plex doesn't recognise as media
(`<name>.ama-partial`), checked against its source, then renamed into place, so
Plex never sees a partially written file. Filing the same files again is a
no-op for files already in place, so an interrupted filing is simply re-run.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from ama.config import LibraryKind, Library, library_for

PARTIAL = ".ama-partial"
NAME_LIMIT = 80  # characters per folder/file name, keeps paths under Windows' MAX_PATH

_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM\d|LPT\d)(\..*)?$", re.I)


class FilingError(Exception):
    """A file couldn't be put into the Archive intact."""


def safe_chars(text: str) -> str:
    """`text` with the characters Windows forbids in a name (`/` too) -> `_`."""
    return _ILLEGAL.sub("_", text)


def safe_name(text: str, limit: int = NAME_LIMIT) -> str:
    """`text` as a Windows/SMB-safe file or folder name (characters Windows forbids -> `_`)."""
    name = _ILLEGAL.sub("_", text).strip()
    name = name[:limit].rstrip(" .") or "_"
    return f"{name}_" if _RESERVED.match(name) else name


def extended_path(path: Path) -> Path:
    """On Windows, `path` as an extended-length path (`\\\\?\\…`), so the Archive's long
    artist/album/track names aren't cut off by the 260-character MAX_PATH."""
    if os.name != "nt":
        return path
    p = os.path.abspath(path)
    if p.startswith("\\\\?\\"):
        return Path(p)
    return Path("\\\\?\\UNC\\" + p[2:] if p.startswith("\\\\") else "\\\\?\\" + p)


def move(src: Path, dest: Path) -> None:
    """Move a filed file to `dest` inside the Archive (a rename on the share), removing
    `src`'s folder if that leaves it empty. Done already (src gone, dest there) = no-op.
    `dest` must not be another file: it would be replaced."""
    s, d = extended_path(src), extended_path(dest)
    if not s.exists() and d.exists():
        return
    d.parent.mkdir(parents=True, exist_ok=True)
    os.replace(s, d)
    try:
        s.parent.rmdir()
    except OSError:
        pass  # not empty


def _digest(path: Path) -> tuple[int, str]:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return path.stat().st_size, h.hexdigest()


_KIND_OF = {k.folder: k for k in LibraryKind}


def kind_of_path(rel: Path) -> LibraryKind | None:
    """The kind an archiver's logical path (`Movies/…`, `TV/…`, `Music/…`) files as."""
    return _KIND_OF.get(rel.parts[0]) if rel.parts else None


class Archive:
    """The Libraries, each its own folder wherever it is (ADR 0011). `copy` is replaceable
    so tests can break a copy.

    Archivers name folders by kind, as Plex lays them out (`Movies/<film>`, `TV/<show>`,
    `Music/<artist>/<album>`); `folder` puts that under the kind's Library, so a stored
    path keeps meaning the same thing whichever Library holds it."""

    def __init__(self, libraries: Sequence[Library],
                 copy: Callable[[Path, Path], object] = shutil.copyfile) -> None:
        self.libraries = tuple(libraries)  # live: replaced when Settings change them
        self.copy = copy

    def folder(self, rel: Path, library: str | None = None) -> Path:
        """Where `rel` (`Movies/…`, `TV/…`, `Music/…`) is: in the Library the Job picked, else
        its kind's default."""
        kind = kind_of_path(rel)
        if kind is None:
            raise ValueError(f"{rel} isn't under Movies, TV or Music")
        return Path(library_for(self.libraries, kind, library).path, *rel.parts[1:])

    def library_of(self, folder: Path) -> Library | None:
        """The Library holding `folder` (the innermost, if Libraries nest)."""
        holding = [lib for lib in self.libraries if Path(folder).is_relative_to(lib.path)]
        return max(holding, key=lambda lib: len(Path(lib.path).parts), default=None)

    def logical(self, folder: Path) -> Path | None:
        """`folder` as archivers name it (`Movies/<film>`), the reverse of `folder`; None
        outside every Library."""
        library = self.library_of(folder)
        if library is None:
            return None
        return Path(library.kind.folder, *Path(folder).relative_to(library.path).parts)

    def within(self, folder: Path) -> Path | None:
        """`folder` from its Library folder's name down (`Films HD/<film>`); None outside
        every Library."""
        library = self.library_of(folder)
        if library is None:
            return None
        return Path(folder).relative_to(Path(library.path).parent)

    def shown(self, folder: Path) -> str:
        """`folder` as the UI names it: from its Library folder's name down."""
        rel = self.within(folder)
        return str(folder) if rel is None else rel.as_posix()

    def place(self, folder: Path, files: Mapping[str, Path], library: str | None = None) -> Path:
        """Copy `files` ({name: source}) into `folder` (see `folder`), verified byte-identical;
        the folder. Raises FilingError or OSError."""
        folder_path = self.folder(folder, library)
        dest = extended_path(folder_path)
        dest.mkdir(parents=True, exist_ok=True)
        expected = {name: _digest(src) for name, src in files.items()}
        for name, src in files.items():
            final = dest / name
            if final.exists() and _digest(final) == expected[name]:
                continue
            temp = dest / f"{name}{PARTIAL}"
            self.copy(src, temp)
            if _digest(temp) != expected[name]:
                temp.unlink(missing_ok=True)
                raise FilingError(f"{name} didn't copy intact to {folder_path}")
            os.replace(temp, final)
        for name in files:
            final = dest / name
            if not final.exists() or _digest(final) != expected[name]:
                raise FilingError(f"{name} isn't intact in {folder_path}")
        return folder_path
