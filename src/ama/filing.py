"""The steps every archiver takes around filing into a Library folder."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx

from ama.archive import Archive, FilingError
from ama.jobs import JobStore
from ama.plex import Plex
from ama.problems import Problem
from ama.retry import RetryLater


@contextmanager
def to_library(archive: Archive, rel: Path, library: str | None) -> Iterator[None]:
    """Copying into `rel`'s Library folder: its failures wait as a Problem naming the folder."""
    where = archive.folder(Path(rel.parts[0]), library)
    try:
        yield
    except FilingError as e:
        raise RetryLater(f"Couldn't file to {where} ({e})") from e
    except OSError as e:
        if isinstance(e, FileNotFoundError) and not _within(e.filename, where):
            raise  # a source gone from Scratch: no wait for the Library folder fixes that
        if not os.path.isdir(where):
            raise RetryLater(f"Can't reach the Library folder {where}", Problem.LIBRARY_FOLDER,
                             f"Can't reach {where}") from e
        cause = e.strerror or str(e)
        raise RetryLater(f"Couldn't file to the Library folder {where}: {cause}",
                         Problem.LIBRARY_FOLDER, f"{where}: {cause}") from e


def _within(filename: object, folder: Path) -> bool:
    if not isinstance(filename, str):
        return True
    for prefix, plain in (("\\\\?\\UNC\\", "\\\\"), ("\\\\?\\", "")):
        if filename.startswith(prefix):
            filename = plain + filename[len(prefix):]
            break
    return Path(filename).is_relative_to(folder)


def scan(plex: Plex, jobs: JobStore, job_id: int, folder: Path) -> None:
    """Ask Plex to scan `folder`, logging the outcome; a failure never un-files anything."""
    try:
        jobs.log(job_id, plex.scan(folder))
    except httpx.HTTPError as e:
        jobs.log(job_id, f"Couldn't ask Plex to scan the folder ({e}); "
                           "Plex will find it on its next scan", error=True)
    finally:
        jobs.finish_run(job_id)
