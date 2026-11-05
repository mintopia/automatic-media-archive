"""Inline output on Now (DESIGN.md "Logs" > "Inline output on Now"): the newest lines of a
Job's running Step, for the rip card and the running Encoding row, and where that Step is
in Logs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ama.runs import OutputLine

if TYPE_CHECKING:
    from ama.app import Services

TAIL_LINES = 20


@dataclass(frozen=True)
class StepOutput:
    step_id: int
    href: str  # the Step on its Job's run page: /logs/jobs/7#step-encode-1
    lines: list[OutputLine]


def step_output(services: Services, job_id: int, key: str) -> StepOutput | None:
    """The Job's Step `key` ("rip", "encode:1") while it runs, else None (no toggle)."""
    step = services.runs.running_step(job_id, key)
    if step is None:
        return None
    return StepOutput(step, f"/logs/jobs/{job_id}#step-{key.replace(':', '-')}",
                      tail(services, step))


def tail(services: Services, step_id: int) -> list[OutputLine]:
    return services.runs.tail(step_id)[-TAIL_LINES:]
