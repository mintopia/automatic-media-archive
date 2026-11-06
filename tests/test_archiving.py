"""Archiving into a Library folder (#48): which failures wait for the folder, and why."""

from __future__ import annotations

import errno
from pathlib import Path

import pytest

from ama import archiving
from ama.archive import Archive
from ama.config import Library, LibraryKind
from ama.problems import Problem
from ama.retry import RetryLater

REL = Path("Movies/Example Movie (2016)")


def _archive(tmp_path, copy=None) -> tuple[Archive, Path]:
    movies = tmp_path / "libraries" / "Movies"
    libs = [Library(name=k.folder, kind=k, path=str(tmp_path / "libraries" / k.folder),
                    default=True) for k in LibraryKind]
    return (Archive(libs, copy=copy) if copy else Archive(libs)), movies


def _source(tmp_path) -> Path:
    src = tmp_path / "scratch" / "encode.mkv"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"film" * 1000)
    return src


def _file(archive: Archive, src: Path) -> None:
    with archiving.to_library(archive, REL, None):
        archive.place(REL, {"Example Movie (2016).mkv": src})


def test_a_source_missing_from_scratch_is_not_a_library_folder_problem(tmp_path):
    archive, _ = _archive(tmp_path)
    with pytest.raises(FileNotFoundError):
        _file(archive, tmp_path / "scratch" / "gone.mkv")


def test_an_unreachable_library_folder_waits_and_names_it(tmp_path):
    archive, movies = _archive(tmp_path)
    movies.parent.mkdir(parents=True)
    movies.write_bytes(b"")  # a file where the folder should be, like a dropped drive
    with pytest.raises(RetryLater) as caught:
        _file(archive, _source(tmp_path))
    assert str(caught.value) == f"Can't reach the Library folder {movies}"
    assert caught.value.problem == Problem.LIBRARY_FOLDER
    assert caught.value.detail == f"Can't reach {movies}"


@pytest.mark.parametrize("error", [OSError(errno.ENOSPC, "No space left on device"),
                                   PermissionError(errno.EACCES, "Access is denied")])
def test_a_reachable_library_folder_that_refuses_the_file_waits_and_says_why(tmp_path, error):
    def failing_copy(src, dest):
        raise error

    archive, movies = _archive(tmp_path, copy=failing_copy)
    with pytest.raises(RetryLater) as caught:
        _file(archive, _source(tmp_path))
    assert str(caught.value) == (f"Couldn't archive to the Library folder {movies}: "
                                 f"{error.strerror}")
    assert caught.value.problem == Problem.LIBRARY_FOLDER
    assert caught.value.detail == f"{movies}: {error.strerror}"
    assert "Can't reach" not in str(caught.value)
