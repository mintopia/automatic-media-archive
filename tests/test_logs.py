"""Logs (#32): every Job's Run with its Steps and their output, and app events as Runs.
The real app with fakes: a film ripped, identified, Encoded and filed; a CD that fails;
startup, a NAS drop and tool downloads."""

from __future__ import annotations

import hashlib
import html
import re

from fastapi.testclient import TestClient

from ama.app import create_app
from ama.drive import DiscType
from ama.jobs import JobStatus
from ama.runs import RunKind
from ama.tools import Member, Pin
from tests.conftest import eventually, make_harness
from tests.fakes import FakeFetch


def _film(harness) -> int:
    harness.web.add_film("Example Movie", 1234, "Example Movie", runtime=122)
    harness.makemkv.release()
    harness.drive.insert(DiscType.BD, "EXAMPLE_MOVIE")
    eventually(lambda: harness.services.jobs.list(JobStatus.FILED))
    job = harness.services.jobs.list(JobStatus.FILED)[0]
    run = harness.services.runs.job_run(job.id)
    eventually(lambda: harness.services.runs.get_run(run).finished_at is not None)
    return job.id


def _text(page: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", page))


def _step(page: str, anchor: str) -> str:
    """One Step's markup on a run page."""
    m = re.search(rf'<(details|div) class="step" id="{anchor}".*?</\1>', page, re.S)
    assert m, f"no step {anchor}"
    return m.group(0)


def test_a_filed_films_run_lists_each_step_with_its_tool_result_and_stored_output(
        client, harness):
    job_id = _film(harness)
    r = client.get(f"/logs/jobs/{job_id}", follow_redirects=True)
    assert r.status_code == 200
    page = r.text
    assert "Example Movie (2016)" in page
    assert '<span class="stk fil"' in page or 'class="stk fil"' in page
    rip = _text(_step(page, "step-rip"))
    assert "Rip" in rip and "makemkvcon" in rip
    encode = _step(page, "step-encode-1")
    text = _text(encode)
    assert "Main Feature, Title 1" in text and "ffmpeg" in text
    assert "Finished, exit code 0" in text
    # ffmpeg's own non-progress output is kept, progress blocks are not
    assert "a harmless warning" in text
    assert "out_time_us" not in text and "progress=continue" not in text
    # ...and so is what AMA said about the Encode
    assert "Encoding Title 1 as Example Movie (2016)" in text
    ident = _text(_step(page, "step-identify"))
    assert "Identified as Example Movie (2016)" in ident
    assert "Filed" in _text(_step(page, "step-file"))


def test_finished_steps_show_their_stored_output_after_a_restart(tmp_path):
    first = make_harness(tmp_path)
    with TestClient(create_app(first.services)):
        job_id = _film(first)
    again = make_harness(tmp_path)  # a new process on the same database
    with TestClient(create_app(again.services)) as client:
        page = client.get(f"/logs/jobs/{job_id}", follow_redirects=True).text
    assert "a harmless warning" in _text(_step(page, "step-encode-1"))


def test_the_run_list_bins_runs_by_day_and_filters_jobs_app_and_problems(client, harness):
    _film(harness)
    harness.cyanrip.read_errors_in = 2
    harness.drive.insert(DiscType.CD)
    eventually(lambda: harness.services.jobs.list(JobStatus.FAILED))
    eventually(lambda: any(r.title == "AMA started" and r.finished_at
                           for r in harness.services.runs.list_runs()))
    page = client.get("/logs").text
    text = _text(page)
    assert "Today" in text
    assert "Example Movie (2016)" in text and "AMA started" in text
    assert "Unknown CD" in text and "Rip failed" in text
    jobs = _text(client.get("/logs?kind=jobs").text)
    assert "Example Movie (2016)" in jobs and "AMA started" not in jobs
    app = _text(client.get("/logs?kind=app").text)
    assert "AMA started" in app and "Example Movie (2016)" not in app
    problems = _text(client.get("/logs?problems=1").text)
    assert "Unknown CD" in problems and "Example Movie (2016)" not in problems


def test_a_failed_rip_marks_its_error_lines_and_later_steps_didnt_run(client, harness):
    harness.cyanrip.read_errors_in = 2
    harness.drive.insert(DiscType.CD)
    eventually(lambda: harness.services.jobs.list(JobStatus.FAILED))
    job = harness.services.jobs.list(JobStatus.FAILED)[0]
    page = client.get(f"/logs/jobs/{job.id}", follow_redirects=True).text
    rip = _step(page, "step-rip")
    assert "<details" in rip and " open" in rip.split(">", 1)[0]
    assert "errline" in rip and "First error" in rip
    assert 'class="notice"' in page and job.failure.headline in html.unescape(page)
    ident = _step(page, "step-identify")
    assert "<details" not in ident and "Didn't run" in html.unescape(ident)


def test_a_running_steps_output_is_streamed_from_its_ring(client, harness):
    harness.web.add_film("Example Movie", 1234, "Example Movie", runtime=122)
    harness.ffmpeg.hold = True
    harness.makemkv.release()
    harness.drive.insert(DiscType.BD, "EXAMPLE_MOVIE")
    eventually(lambda: harness.ffmpeg.encoding.is_set())
    job = harness.services.jobs.list(JobStatus.RIPPED)[0]
    run = harness.services.runs.job_run(job.id)
    page = client.get(f"/logs/runs/{run}").text
    encode = _step(page, "step-encode-1")
    assert "Following live output" in encode and 'role="log"' in encode
    sig = re.search(r'data-sig="([^"]+)"', page).group(1)
    step = re.search(r'data-step="(\d+)"', encode).group(1)
    last = max(int(n) for n in re.findall(rf'id="s{step}-L(\d+)"', encode))
    harness.services.jobs.step_output(job.id, "a new line from ffmpeg")
    live = client.get(f"/logs/runs/{run}/live", params={"sig": sig, f"after_{step}": last})
    assert live.status_code == 200 and "HX-Refresh" not in live.headers
    assert "a new line from ffmpeg" in live.text
    assert f'beforeend:#log-{step}' in live.text
    assert f"s{step}-L{last + 1}" in live.text and f"s{step}-L{last}\"" not in live.text
    # once the page's Steps are out of date, it reloads
    harness.ffmpeg.release()
    eventually(lambda: harness.services.jobs.get(job.id).status == JobStatus.FILED)
    stale = client.get(f"/logs/runs/{run}/live", params={"sig": sig})
    assert stale.headers.get("HX-Refresh") == "true"


def test_startup_is_a_run_with_a_step_for_settings_the_nas_and_each_tool(client, harness):
    eventually(lambda: any(r.title == "AMA started" and r.finished_at
                           for r in harness.services.runs.list_runs()))
    run = next(r for r in harness.services.runs.list_runs() if r.title == "AMA started")
    assert run.kind == RunKind.APP and run.failed is False
    names = [s.name for s in harness.services.runs.steps(run.id)]
    assert names == ["Read settings", "Connect to the NAS", "Check MakeMKV", "Get ffmpeg",
                     "Get cyanrip", "Test encoders"]
    page = _text(client.get(f"/logs/runs/{run.id}").text)
    assert "App event: startup" in page and "Connected to" in page
    assert "hevc_nvenc works" in page and "Configured encoder: HEVC (NVIDIA)" in page


def test_testing_the_encoders_again_is_a_run_of_its_own(client, harness):
    eventually(lambda: any(r.title == "AMA started" and r.finished_at
                           for r in harness.services.runs.list_runs()))
    harness.services.encoders.request()
    eventually(lambda: any(r.title == "Tested the encoders" and r.finished_at
                           for r in harness.services.runs.list_runs()))


def test_a_nas_drop_and_reconnect_is_a_run_of_its_own(client, harness):
    eventually(lambda: any(r.title == "AMA started" and r.finished_at
                           for r in harness.services.runs.list_runs()))
    harness.share["reachable"] = False
    eventually(lambda: any(r.kind == RunKind.NAS for r in harness.services.runs.list_runs()))
    harness.share["reachable"] = True
    eventually(lambda: any(r.kind == RunKind.NAS and r.finished_at
                           for r in harness.services.runs.list_runs()))
    run = next(r for r in harness.services.runs.list_runs() if r.kind == RunKind.NAS)
    assert run.title == "Lost the NAS, then reconnected" and run.failed is False
    assert [s.name for s in harness.services.runs.steps(run.id)] == ["Hold filing", "Reconnect"]


def test_a_failed_download_is_a_failed_startup_and_the_retry_that_fixed_it_is_linked(tmp_path):
    exe = b"pretend cyanrip"
    sha = hashlib.sha256(exe).hexdigest()
    pin = Pin("cyanrip", "1", "https://example/cyanrip.exe", sha, (Member("cyanrip", None, sha),))
    fetch = FakeFetch({pin.url: exe})
    fetch.fail_once(pin.url, TimeoutError("timed out"))
    h = make_harness(tmp_path, fetch=fetch, pins=(pin,))
    with TestClient(create_app(h.services)) as client:
        runs = h.services.runs
        eventually(lambda: any(r.kind == RunKind.TOOLS and r.finished_at
                               for r in runs.list_runs()))
        startup = next(r for r in runs.list_runs() if r.title == "AMA started")
        assert startup.failed is True
        page = html.unescape(client.get(f"/logs/runs/{startup.id}").text)
        fixed = next(r for r in runs.list_runs() if r.kind == RunKind.TOOLS)
        assert f'href="/logs/runs/{fixed.id}"' in page
        assert "timed out" in page


def test_no_command_line_or_secret_reaches_any_step_output(tmp_path):
    h = make_harness(tmp_path, password="hunter2-pass")
    with TestClient(create_app(h.services)):
        _film(h)
        h.share["reachable"] = False
        eventually(lambda: any(r.kind == RunKind.NAS for r in h.services.runs.list_runs()))
        job = h.services.jobs.list(JobStatus.FILED)[0]
        h.services.jobs.log(job.id, "oops: hunter2-pass")  # even if something says it
        out = []
        for run in h.services.runs.list_runs():
            for s in h.services.runs.steps(run.id):
                out += [ln.text for ln in h.services.runs.output(s.id)]
        # the arguments that say something: paths, filters, metadata (key=value)
        args = {a for c in h.ffmpeg.encodes() + h.makemkv.calls for a in c[1:]
                if any(ch in a for ch in "\\/=:")}
        joined = "\n".join(out)
        assert "hunter2-pass" not in joined and "tmdb-key" not in joined
        assert args and not [a for a in args if a in joined], "a command-line argument was logged"


def test_logs_is_in_the_top_bar_menu(client):
    page = client.get("/").text
    assert re.search(r'<a class="mi" href="/logs">.*?Logs</a>', page, re.S)
    logs = client.get("/logs").text
    assert re.search(r'<a class="mi" href="/logs" aria-current="page">', logs)


def test_a_steps_output_downloads_as_text(client, harness):
    job_id = _film(harness)
    run = harness.services.runs.job_run(job_id)
    step = next(s for s in harness.services.runs.steps(run) if s.key == "encode:1")
    r = client.get(f"/logs/steps/{step.id}/download")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    assert "a harmless warning" in r.text
