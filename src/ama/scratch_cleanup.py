"""Scratch cleanup (GLOSSARY): removing kept Scratch of finished Jobs, oldest first."""

from __future__ import annotations

import asyncio
import logging
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from ama.jobs import Failure, FailureKind, JobRecord, JobStore, format_gb
from ama.runs import RunKind, Runs
from ama.scratch import GB, dir_bytes

log = logging.getLogger(__name__)

CUT_OFF = "finishing a cleanup cut off by a restart"


@dataclass(frozen=True)
class Removal:
    """One Job's Scratch to remove, and the rule that took it."""

    job: JobRecord
    rule: str


@dataclass(frozen=True)
class Cleanup:
    """What one cleanup takes; `short_of_floor_gb` is the floor free space is still below
    once all of it is gone."""

    removals: list[Removal]
    short_of_floor_gb: int | None = None


def _failure(kept: str) -> Failure:
    return Failure(FailureKind.SCRATCH_CLEANED,
                   "The Encode didn't work, and its Rip was removed from Scratch.",
                   f"It was kept {kept} for a retry. Put the Disc back in to rip it again.")


class ScratchCleaner:
    HOUR = 3600.0

    def __init__(self, jobs: JobStore, runs: Runs, retention_days: Callable[[], int],
                 floor_gb: Callable[[], int] = lambda: 0,
                 free: Callable[[], int | None] = lambda: None,
                 now: Callable[[], datetime] = datetime.now, interval: float = HOUR,
                 size: Callable[[Path], int] = dir_bytes) -> None:
        self._jobs = jobs
        self._runs = runs
        self._retention_days = retention_days  # read each time: a saved change applies
        self._floor_gb = floor_gb
        self._free = free  # free bytes on Scratch; None when it can't be read
        self._now = now
        self._size = size
        self.interval = interval
        self._wake = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None

    def claim(self) -> Cleanup:
        """Take every Job whose Scratch is due for removal: those a cut-off cleanup left,
        then those past the retention age, then, while free space is below the floor, the
        rest, oldest first."""
        out = [Removal(job, CUT_OFF) for job in self._jobs.scratch_left()]
        days = self._retention_days()
        if days > 0:
            rule = f"older than {days} days"
            for job in self._jobs.kept_scratch(self._now() - timedelta(days=days)):
                if self._jobs.mark_scratch_cleaned(job.id, _failure(f"{days} days")):
                    out.append(Removal(job, rule))
        floor_gb = self._floor_gb()
        free = self._free() if floor_gb > 0 else None
        if free is None:
            return Cleanup(out)
        free += sum(self._size(r.job.scratch_dir) for r in out)
        rule = f"Scratch below the {floor_gb} GB floor"
        for job in self._jobs.kept_scratch(datetime.max):
            if free >= floor_gb * GB:
                break
            if self._jobs.mark_scratch_cleaned(job.id, _failure("until Scratch ran low")):
                out.append(Removal(job, rule))
                free += self._size(job.scratch_dir)
        return Cleanup(out, floor_gb if free < floor_gb * GB else None)

    def remove(self, cleanup: Cleanup) -> None:
        """Remove the claimed Scratch, as one Run in Logs."""
        removals = cleanup.removals
        if not removals:
            if cleanup.short_of_floor_gb is not None:
                log.warning("scratch: below the %d GB floor, nothing to remove",
                            cleanup.short_of_floor_gb)
            return
        run = self._runs.start_run(RunKind.SCRATCH, "Cleaned up Scratch", item="scratch")
        total = 0
        for r in removals:
            job = r.job
            step = self._runs.begin(run, f"job:{job.id}", "Remove Scratch",
                                    subject=f"{job.name} (Job {job.id})")
            size = self._size(job.scratch_dir)
            self._runs.line(step, f"Removing {job.scratch_dir} ({r.rule})")
            shutil.rmtree(job.scratch_dir, ignore_errors=True)
            total += size
            self._runs.end(step, failed=job.scratch_dir.exists(),
                           result=f"{format_gb(size)} · {r.rule}")
        n = len(removals)
        detail = f"{n} Job{'s' if n != 1 else ''} · {format_gb(total)} freed"
        if cleanup.short_of_floor_gb is not None:
            detail += (f" · still below the {cleanup.short_of_floor_gb} GB floor, "
                       "nothing else to remove")
        self._runs.finish_run(run, failed=False, detail=detail)

    def clean(self) -> None:
        self.remove(self.claim())

    def request(self) -> None:
        """Clean up now (from any thread); a no-op before `run` starts, which cleans first."""
        loop = self._loop
        if loop is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(self._wake.set)
            except RuntimeError:  # the loop closed meanwhile
                pass

    async def run(self) -> None:
        """Claims before its first await: listed ahead of the archivers, it runs before
        they queue failed Encodes again at startup."""
        self._loop = asyncio.get_running_loop()
        while True:
            self._wake.clear()
            try:
                cleanup = self.claim()
                await asyncio.to_thread(self.remove, cleanup)
            except Exception:  # noqa: BLE001 - never kill the loop; try again next time
                log.exception("scratch: cleanup went wrong")
            try:
                await asyncio.wait_for(self._wake.wait(), self.interval)
            except TimeoutError:
                pass
