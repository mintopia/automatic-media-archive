"""Runs and Steps (GLOSSARY): what Logs stores about each tool run."""

from __future__ import annotations

from datetime import datetime, timedelta

from ama.db import Database
from ama.events import EventBus
from ama.runs import RunKind, Runs, StepState


class Clock:
    def __init__(self) -> None:
        self.t = datetime(2026, 11, 5, 9, 58, 0)

    def __call__(self) -> datetime:
        return self.t

    def tick(self, seconds: float) -> None:
        self.t += timedelta(seconds=seconds)


def make_runs(tmp_path, clock=None, secrets=lambda: ()) -> Runs:
    return Runs(Database(tmp_path / "ama.sqlite3"), EventBus(), secrets=secrets,
                now=clock or Clock())


def test_a_finished_step_keeps_its_output_result_and_exit_code_after_a_restart(tmp_path):
    clock = Clock()
    runs = make_runs(tmp_path, clock)
    run = runs.start_run(RunKind.APP, "AMA started", item="startup")
    step = runs.begin(run, "ffmpeg", "Get ffmpeg", tool="ffmpeg 9.0.2")
    runs.line(step, "Downloading ffmpeg 9.0.2")
    clock.tick(14)
    runs.line(step, "The download failed its SHA-256 check", error=True)
    runs.end(step, failed=True, exit_code=1, result="Download failed")
    runs.finish_run(run, failed=True)

    again = make_runs(tmp_path, clock)  # a new process on the same database
    [got] = again.list_runs()
    assert (got.kind, got.title, got.failed) == (RunKind.APP, "AMA started", True)
    [s] = again.steps(got.id)
    assert (s.name, s.tool, s.result, s.state, s.exit_code) == (
        "Get ffmpeg", "ffmpeg 9.0.2", "Download failed", StepState.FAILED, 1)
    assert s.took == timedelta(seconds=14)
    assert [(ln.text, ln.error) for ln in again.output(s.id)] == [
        ("Downloading ffmpeg 9.0.2", False), ("The download failed its SHA-256 check", True)]
    assert (s.lines, s.errors) == (2, 1)


def test_a_running_step_streams_its_recent_lines_from_memory(tmp_path):
    runs = make_runs(tmp_path)
    run = runs.start_run(RunKind.TOOLS, "Getting cyanrip", item="cyanrip")
    step = runs.begin(run, "cyanrip", "Get cyanrip")
    for n in range(Runs.RING + 5):
        runs.line(step, f"line {n}")
    tail = runs.tail(step)
    assert len(tail) == Runs.RING
    assert tail[-1].text == f"line {Runs.RING + 4}" and tail[-1].n == Runs.RING + 5
    assert runs.steps(run)[0].lines == Runs.RING + 5  # the count is all of them


def test_secrets_never_reach_stored_output(tmp_path):
    runs = make_runs(tmp_path, secrets=lambda: ("hunter2", ""))
    run = runs.start_run(RunKind.NAS, "Lost the NAS", item="nas")
    step = runs.begin(run, "reconnect", "Reconnect")
    runs.line(step, "net use said: bad password hunter2")
    assert runs.output(step)[0].text == "net use said: bad password •••"
    assert runs.tail(step)[0].text == "net use said: bad password •••"


def test_a_restart_ends_whatever_was_running(tmp_path):
    runs = make_runs(tmp_path)
    run = runs.start_run(RunKind.APP, "AMA started", item="startup")
    step = runs.begin(run, "nas", "Connect to the NAS")

    again = make_runs(tmp_path)
    again.recover()
    [s] = again.steps(run)
    assert s.state == StepState.FAILED and s.result == "AMA stopped before this finished"
    assert again.get_run(run).failed is True
    assert step == s.id


def test_a_restart_lets_a_jobs_running_step_carry_on(tmp_path):
    runs = make_runs(tmp_path)
    runs._db.execute("INSERT INTO jobs (id, disc_type, status, scratch_dir, started_at) "
                     "VALUES (3, 'BD', 'ripped', '', '2026-11-05T10:00:00')")
    runs.job_begin(3, "encode:1", "Encode")
    runs.job_note(3, "before the restart")
    runs.flush()  # as the app does within a second, and when it stops

    again = make_runs(tmp_path)
    again.recover()
    again.job_note(3, "after it")
    [s] = again.steps(again.job_run(3))
    assert s.state == StepState.RUNNING
    assert [ln.text for ln in again.tail(s.id)] == ["before the restart", "after it"]


def test_a_job_has_one_run_whose_steps_follow_one_another(tmp_path):
    runs = make_runs(tmp_path)
    db = runs._db
    db.execute("INSERT INTO jobs (id, disc_type, status, scratch_dir, started_at) "
               "VALUES (7, 'CD', 'ripping', '', '2026-11-05T10:00:00')")
    runs.job_begin(7, "rip", "Rip", tool="cyanrip")
    runs.job_note(7, "Track 1 done")
    runs.job_begin(7, "identify", "Identification")  # ends the Rip
    runs.job_note(7, "Identified as Kid A")
    runs.job_end(7, finish=True)
    run = runs.job_run(7)
    rip, ident = runs.steps(run)
    assert (rip.key, rip.state, [ln.text for ln in runs.output(rip.id)]) == (
        "rip", StepState.DONE, ["Track 1 done"])
    assert (ident.key, ident.state) == ("identify", StepState.DONE)
    assert runs.get_run(run).failed is False


def test_beginning_a_step_again_starts_its_output_afresh(tmp_path):
    """An Encode cut short by a restart runs again: its step shows the new attempt."""
    runs = make_runs(tmp_path)
    run = runs.start_run(RunKind.APP, "x")
    step = runs.begin(run, "s", "S")
    runs.line(step, "first try")
    again = runs.begin(run, "s", "S")
    runs.line(again, "second try")
    assert again == step
    assert [ln.text for ln in runs.output(step)] == ["second try"]
