"""Configurable log pruning (#34): `logs.keep_days` removes old Step output, at startup,
daily and as soon as it's saved; Runs, Steps and their results stay and say so."""

from __future__ import annotations

import asyncio
import html
import re
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from ama.app import create_app
from ama.db import Database
from ama.events import EventBus
from ama.runs import LogPruner, RunKind, Runs
from tests.conftest import eventually, make_harness, write_config


def _text(page: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page)))


def _old_run(runs: Runs, days_ago: int) -> tuple[int, int]:
    """A finished tools Run with one Step of output, as if it ran `days_ago` days ago."""
    run = runs.start_run(RunKind.TOOLS, "Got cyanrip", item="cyanrip")
    step = runs.begin(run, "cyanrip", "Get cyanrip", tool="cyanrip")
    runs.line(step, "Downloading cyanrip 0.9.2")
    runs.end(step, result="Downloaded")
    runs.finish_run(run, failed=False)
    then = (datetime.now() - timedelta(days=days_ago)).isoformat(timespec="milliseconds")
    runs.flush()
    # Test setup only: back-date the Run, as no clock is injected into the app.
    runs._db.execute("UPDATE steps SET started_at = ?, finished_at = ? WHERE id = ?",
                     (then, then, step))
    runs._db.execute("UPDATE runs SET started_at = ?, finished_at = ? WHERE id = ?",
                     (then, then, run))
    return run, step


def test_saving_keep_days_in_settings_removes_old_output_at_once(tmp_path):
    toml = write_config(tmp_path)
    h = make_harness(tmp_path, config_file=toml)
    runs = h.services.runs
    old_run, old = _old_run(runs, 20)
    _, recent = _old_run(runs, 3)
    with TestClient(create_app(h.services)) as client:
        page = _text(client.get("/settings/logs").text)
        assert "Keep step output for" in page and "Takes effect at once" in page
        assert "0 keeps it forever" in page
        assert "Step output is kept until you remove it" in _text(client.get("/logs").text)

        r = client.post("/settings/logs", data={"logs.keep_days": "14"},
                        follow_redirects=False)
        assert r.status_code == 303
        assert "keep_days = 14" in toml.read_text(encoding="utf-8")
        eventually(lambda: runs.output(old) == [])
        assert [ln.text for ln in runs.output(recent)] == ["Downloading cyanrip 0.9.2"]

        run_page = client.get(f"/logs/runs/{old_run}").text
        step = _text(re.search(r'<details class="step" id="step-cyanrip".*?</details>',
                               run_page, re.S).group(0))
        assert "Get cyanrip" in step and "Downloaded" in step  # its header stays
        assert "Output removed after 14 days." in step and "Keep output longer" in step
        assert 'href="/settings/logs"' in run_page
        today = datetime.now()
        assert f"Removed {today.day} {today:%b}" in _text(run_page)

        listing = _text(client.get("/logs").text)
        assert "output removed after 14 days" in listing
        assert "Output older than 14 days is removed" in listing


def test_old_output_is_removed_at_startup(tmp_path):
    toml = write_config(tmp_path, extra="\n[logs]\nkeep_days = 7\n")
    first = make_harness(tmp_path, config_file=toml)
    _, old = _old_run(first.services.runs, 8)
    again = make_harness(tmp_path, config_file=toml)
    with TestClient(create_app(again.services)):
        eventually(lambda: again.services.runs.output(old) == [])
    assert again.services.runs.get_step(old).removed.days == 7


def test_the_pruner_runs_again_each_interval_with_the_setting_as_it_is_then(tmp_path):
    runs = Runs(Database(tmp_path / "ama.sqlite3"), EventBus())
    keep = {"days": 0}
    _, old = _old_run(runs, 2)
    pruner = LogPruner(runs, lambda: keep["days"], interval=0.01)

    async def go() -> None:
        task = asyncio.create_task(pruner.run())
        await asyncio.sleep(0.05)
        assert runs.output(old) != []  # 0 keeps everything
        keep["days"] = 1
        for _ in range(100):
            await asyncio.sleep(0.01)
            if not runs.output(old):
                break
        task.cancel()

    asyncio.run(go())
    assert runs.output(old) == []
