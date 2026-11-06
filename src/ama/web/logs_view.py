"""What the Logs pages show (docs/mockups/logs*.html): the run list and one Run's Steps.

A Job's Run lists the Job's Steps as its page does (`job_steps`), each with the output
and exit code `runs.py` stored under the same key; an app event's Run is all stored.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from ama.drive import DiscType
from ama.encode import EncodeProgress
from ama.jobs import JobRecord, JobStatus
from ama.phase import Phase
from ama.runs import Removed, RunKind, RunRecord, StepRecord
from ama.web.job_steps import Step, job_phase, job_steps

if TYPE_CHECKING:
    from ama.app import Services

# An app event's kind on its row and page: (icon, label, "App event: <what>").
APP_KINDS = {RunKind.APP: ("power", "App", "startup"), RunKind.NAS: ("drive", "NAS", "NAS"),
             RunKind.TOOLS: ("layers", "Tools", "tools"),
             RunKind.SCRATCH: ("drive", "Scratch", "Scratch cleanup")}


def took(delta: timedelta | None) -> str:
    """ "0.1 s", "57 s", "1 min 12 s", "38 min", "2 h 8 min"."""
    if delta is None:
        return ""
    s = delta.total_seconds()
    if s < 1:
        return f"{max(s, 0):.1f} s"
    if s < 60:
        return f"{round(s)} s"
    if s < 600:
        m, rest = divmod(round(s), 60)
        return f"{m} min {rest} s" if rest else f"{m} min"
    m = round(s / 60)
    return f"{m // 60} h {m % 60} min" if m >= 60 else f"{m} min"


def day_name(day: date, today: date) -> str:
    if day == today:
        return "Today"
    if day == today - timedelta(days=1):
        return "Yesterday"
    return f"{day:%a} {day.day} {day:%b}"


def when(at: datetime, today: date) -> str:
    """ "today 17:20", "yesterday 19:02", "Tue 20 Oct, 20:14"."""
    name = day_name(at.date(), today)
    return f"{name.lower()} {at:%H:%M}" if name in ("Today", "Yesterday") \
        else f"{name}, {at:%H:%M}"


@dataclass(frozen=True)
class StepView:
    key: str
    name: str
    subject: str
    state: str          # done | running | waiting | failed | notrun
    detail: str         # "ffmpeg 9.0.2 · Encoded · waiting to be archived"
    duration: str       # "41 min" ("" when it hasn't started)
    stored: StepRecord | None = None
    progress: EncodeProgress | None = None
    colour: str = ""    # rip | enc while running

    @property
    def anchor(self) -> str:
        """The Step's id on its run page: `step-encode-1`, `step-rip`."""
        return "step-" + self.key.replace(":", "-")

    @property
    def has_output(self) -> bool:
        return self.stored is not None and self.state not in ("waiting", "notrun")

    @property
    def removed(self) -> Removed | None:
        """When its output was pruned (#34), if it was."""
        return self.stored.removed if self.has_output and self.stored else None


@dataclass(frozen=True)
class RunView:
    run: RunRecord
    title: str
    steps: list[StepView]
    job: JobRecord | None = None
    phase: Phase | None = None   # a Job's
    errors: int = 0
    meta: str = ""               # the run row's meta line
    notice: tuple[str, str] | None = None  # (headline, more) on a failed Run
    fixed_by: RunRecord | None = None
    sub: str = ""                # the run page's line under the h1

    @property
    def kind_icon(self) -> tuple[str, str, str]:
        return APP_KINDS.get(self.run.kind, ("power", "App", "startup"))

    @property
    def state(self) -> str:
        """done | running | failed: an app event's mark."""
        if self.run.failed is None:
            return "running"
        return "failed" if self.run.failed else "done"

    @property
    def problem(self) -> bool:
        return self.state == "failed" or self.errors > 0 or self.phase == Phase.FAILED

    @property
    def removed(self) -> Removed | None:
        """The latest removal of any of its Steps' output (#34), if any."""
        gone = [s.removed for s in self.steps if s.removed]
        return max(gone, key=lambda r: r.at) if gone else None

    @property
    def done_count(self) -> int:
        return sum(1 for s in self.steps if s.state == "done")

    @property
    def signature(self) -> str:
        """Changes when any Step's state or the Run's does: the page then reloads."""
        parts = [self.state, str(self.phase)] + [f"{s.key}={s.state}" for s in self.steps]
        return hashlib.sha1("|".join(parts).encode()).hexdigest()[:12]


def _stored_detail(tool: str, detail: str) -> str:
    return " · ".join(p for p in (tool, detail) if p)


def _job_step(s: Step, stored: StepRecord | None, now: datetime) -> StepView:
    state = str(s.state)
    if stored is not None and state == "done" and stored.state == "failed":
        state = "failed"
    detail = _stored_detail(stored.tool if stored else "", s.detail)
    if s.started is not None:
        duration = s.took(now)
    elif stored is not None and state not in ("waiting", "notrun"):
        duration = took((stored.finished_at or now) - stored.started_at)
    else:
        duration = ""
    return StepView(s.key, s.name, s.subject, state, detail, duration, stored, s.progress,
                    s.colour)


def _app_step(st: StepRecord, now: datetime) -> StepView:
    return StepView(st.key, st.name, st.subject, str(st.state),
                    _stored_detail(st.tool, st.result),
                    took((st.finished_at or now) - st.started_at), st,
                    colour="")


def job_title(rec: JobRecord, steps: list[Step]) -> str:
    identified = next((s.subject for s in steps if s.name == "Identification"), "")
    unnamed = "Unknown CD" if rec.disc_type == DiscType.CD else rec.disc_type.long_name
    return rec.title or identified or rec.label or unnamed


def run_view(services: Services, run: RunRecord, now: datetime | None = None) -> RunView:
    now = now or datetime.now()
    v = _run_view(services, run, now)
    return replace(v, sub=_sub(v, now))


def _sub(v: RunView, now: datetime) -> str:
    """ "Blu-ray Job · started today at 17:20 · 1 h 46 min so far",
    "CD Job · today 14:31 to 14:52 · stopped after 21 min", "App event · today 09:58 · took 1 min 12 s"."""
    run, job = v.run, v.job
    what = ("CD Job" if job.disc_type == DiscType.CD else f"{job.disc_type.long_name} Job") \
        if job else "App event"
    start = when(run.started_at, now.date())
    end = run.finished_at
    if end is None:
        at = start.replace(" ", " at ", 1) if start.startswith(("today", "yesterday")) else start
        return f"{what} · started {at} · {took(now - run.started_at)} so far"
    failed = run.failed or v.phase == Phase.FAILED
    span = start if end - run.started_at < timedelta(minutes=1) \
        else f"{start} to {end:%H:%M}"
    return f"{what} · {span} · {'stopped after' if failed else 'took'} {took(end - run.started_at)}"


def _run_view(services: Services, run: RunRecord, now: datetime) -> RunView:
    stored = services.runs.steps(run.id)
    errors = sum(s.errors for s in stored)
    if run.kind == RunKind.JOB and run.job_id is not None \
            and (rec := services.jobs.get(run.job_id)) is not None:
        by_key = {s.key: s for s in stored}
        planned = job_steps(services, rec)
        steps = [_job_step(s, by_key.get(s.key), now) for s in planned]
        phase = job_phase(rec, steps)
        notice = (rec.failure.headline, rec.failure.advice) \
            if rec.status == JobStatus.FAILED and rec.failure else None
        return RunView(run, job_title(rec, planned), steps, rec, phase, errors,
                       _job_meta(rec, steps, phase, errors, now), notice)
    steps = [_app_step(s, now) for s in stored]
    notice = None
    fixed = None
    if run.failed:
        failed = [s for s in stored if s.state == "failed"]
        notice = ("; ".join(s.result for s in failed if s.result) or "Something went wrong",
                  "")
        fixed = services.runs.later_fix(run)
    started = f"{run.started_at:%H:%M}"
    meta = " · ".join(p for p in (run.detail, started,
                                  f"took {took(run.took)}" if run.finished_at else "running")
                     if p)
    return RunView(run, run.title, steps, errors=errors, meta=meta, notice=notice,
                   fixed_by=fixed)


def _job_meta(rec: JobRecord, steps: list[StepView], phase: Phase, errors: int,
              now: datetime) -> str:
    start = f"started {rec.started_at:%H:%M}"
    end = rec.archived_at or (rec.finished_at if rec.status == JobStatus.FAILED else None)
    running = next((s for s in steps if s.state == "running"), None)
    failed = next((s for s in steps if s.state == "failed"), None)
    parts: list[str]
    if rec.status == JobStatus.FAILED and failed is not None:
        parts = [f"{failed.name} failed", f"{rec.started_at:%H:%M} to {end:%H:%M}" if end
                 else start]
    elif rec.status == JobStatus.REVIEW:
        parts = ["Waiting for you in Review", start]
    elif running is not None:
        what = running.name + (f" · {running.subject}" if running.subject else "")
        parts = [what, start, f"{took(now - rec.started_at)} so far"]
    elif end is not None:
        parts = [f"{len(steps)} steps", start, f"took {took(end - rec.started_at)}"]
    else:
        nxt = next((s for s in steps if s.state == "waiting"), None)
        parts = [f"Next: {nxt.name}" if nxt else phase.value, start]
    return " · ".join(parts)  # error lines: the row adds them, in red


def bins(views: list[RunView], today: date) -> list[tuple[str, list[RunView]]]:
    """Runs by the day they started, newest first: [("Today", [...]), ...]."""
    out: list[tuple[str, list[RunView]]] = []
    for v in views:
        name = day_name(v.run.started_at.date(), today)
        if not out or out[-1][0] != name:
            out.append((name, []))
        out[-1][1].append(v)
    return out
