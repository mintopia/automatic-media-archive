"""The steps every archiver takes around filing into a Library folder."""

from __future__ import annotations

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
    """Copying into `rel`'s Library folder: any failure means try again later, and a folder
    that can't be reached is a Problem naming it."""
    where = archive.folder(Path(rel.parts[0]), library)
    try:
        yield
    except FilingError as e:
        raise RetryLater(f"Couldn't file to {where} ({e})") from e
    except OSError as e:
        raise RetryLater(f"Can't reach the Library folder {where}", Problem.LIBRARY_FOLDER,
                         str(where)) from e


def scan(plex: Plex, jobs: JobStore, job_id: int, folder: Path) -> None:
    """Ask Plex to scan `folder`, logging the outcome; a failure never un-files anything."""
    try:
        jobs.log(job_id, plex.scan(folder))
    except httpx.HTTPError as e:
        jobs.log(job_id, f"Couldn't ask Plex to scan the folder ({e}); "
                           "Plex will find it on its next scan", error=True)
    finally:
        jobs.finish_run(job_id)
