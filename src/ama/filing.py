"""The steps every archiver takes around filing to the Archive on the NAS."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx

from ama.archive import FilingError
from ama.jobs import JobStore
from ama.nas import NasConnected, NasMonitor
from ama.plex import Plex
from ama.retry import RetryLater


def require_nas(nas: NasMonitor) -> None:
    """RetryLater unless the NAS is connected."""
    if not isinstance(nas.status, NasConnected):
        raise RetryLater("The NAS isn't connected")


@contextmanager
def to_nas() -> Iterator[None]:
    """Copying to the NAS: any failure means try again later."""
    try:
        yield
    except (OSError, FilingError) as e:
        raise RetryLater(f"Couldn't file to the NAS ({e})") from e


def scan(plex: Plex, jobs: JobStore, job_id: int, folder: Path) -> None:
    """Ask Plex to scan `folder`, logging the outcome; a failure never un-files anything."""
    try:
        jobs.log(job_id, plex.scan(folder))
    except httpx.HTTPError as e:
        jobs.log(job_id, f"Couldn't ask Plex to scan the folder ({e}); "
                           "Plex will find it on its next scan", error=True)
    finally:
        jobs.finish_run(job_id)
