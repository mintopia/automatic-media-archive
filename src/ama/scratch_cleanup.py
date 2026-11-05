"""Scratch cleanup (GLOSSARY): removing kept Scratch of finished Jobs, oldest first.

A failed Encode keeps its Job's Rip on Scratch for a retry. Once the Job last changed
status more than `scratch.retention_days` ago (0 = never), cleanup takes it: the Job
fails for good (`FailureKind.SCRATCH_CLEANED`), keeping its record, and its Scratch is
removed. It runs at startup, hourly, when a Job finishes and when the setting is saved.

Taking the Jobs (`claim`) is quick database work on the event loop, done first thing at
startup so a failed Encode it takes is never queued again; removing the files (`remove`)
runs in a thread, so it never delays a Rip. Each cleanup that removes anything is a Run
in Logs, one Step per Job with its size and the rule that applied. Jobs taken but not
yet removed when AMA stopped are removed by the next cleanup.
"""

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
from ama.scratch import dir_bytes

log = logging.getLogger(__name__)

CUT_OFF = "finishing a cleanup cut off by a restart"


@dataclass(frozen=True)
class Removal:
    """One Job's Scratch to remove, and the rule that took it."""

    job: JobRecord
    rule: str


def _failure(days: int) -> Failure:
    return Failure(FailureKind.SCRATCH_CLEANED,
                   "The Encode didn't work, and its Rip was removed from scratch.",
                   f"It was kept {days} days for a retry. Put the Disc back in to rip it "
                   "again.")


class ScratchCleaner:
    HOUR = 3600.0

    def __init__(self, jobs: JobStore, runs: Runs, retention_days: Callable[[], int],
                 now: Callable[[], datetime] = datetime.now, interval: float = HOUR,
                 size: Callable[[Path], int] = dir_bytes) -> None:
        self._jobs = jobs
        self._runs = runs
        self._retention_days = retention_days  # read each time: a saved change applies
        self._now = now
        self._size = size
        self.interval = interval
        self._wake = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None

    def claim(self) -> list[Removal]:
        """Take every Job whose Scratch is due for removal: those a cut-off cleanup left,
        then those past the retention age, oldest first."""
        out = [Removal(job, CUT_OFF) for job in self._jobs.scratch_left()]
        days = self._retention_days()
        if days <= 0:
            return out
        rule = f"older than {days} days"
        for job in self._jobs.kept_scratch(self._now() - timedelta(days=days)):
            if self._jobs.mark_scratch_cleaned(job.id, _failure(days)):
                out.append(Removal(job, rule))
        return out

    def remove(self, removals: list[Removal]) -> None:
        """Remove the claimed Scratch, as one Run in Logs."""
        if not removals:
            return
        run = self._runs.start_run(RunKind.SCRATCH, "Cleaned up scratch", item="scratch")
        total = 0
        for r in removals:
            job = r.job
            step = self._runs.begin(run, f"job:{job.id}", "Remove scratch",
                                    subject=f"{job.name} (Job {job.id})")
            size = self._size(job.scratch_dir)
            self._runs.line(step, f"Removing {job.scratch_dir} ({r.rule})")
            shutil.rmtree(job.scratch_dir, ignore_errors=True)
            total += size
            self._runs.end(step, failed=job.scratch_dir.exists(),
                           result=f"{format_gb(size)} · {r.rule}")
        n = len(removals)
        self._runs.finish_run(run, failed=False,
                              detail=f"{n} Job{'s' if n != 1 else ''} · {format_gb(total)} freed")

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
                removals = self.claim()
                await asyncio.to_thread(self.remove, removals)
            except Exception:  # noqa: BLE001 - never kill the loop; try again next time
                log.exception("scratch: cleanup went wrong")
            try:
                await asyncio.wait_for(self._wake.wait(), self.interval)
            except TimeoutError:
                pass
