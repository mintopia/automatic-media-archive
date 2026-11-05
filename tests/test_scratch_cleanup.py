"""Scratch cleanup by age (#53): kept Scratch of finished Jobs (failed Encodes) older than
`scratch.retention_days` is removed, oldest first, and recorded as a Run in Logs."""

from __future__ import annotations

import html
import re
import threading
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath

from fastapi.testclient import TestClient

from ama.app import create_app
from ama.db import Database
from ama.drive import DiscType
from ama.encoder import EncodeStatus
from ama.events import EventBus
from ama.jobs import FailureKind, JobStatus, JobStore, ReviewReason
from ama.moviearchive import Movies
from ama.runs import RunKind, Runs
from ama.scratch_cleanup import ScratchCleaner
from ama.tmdb import Candidate, Series
from ama.tv import Episode
from ama.tvarchive import TvTitles
from tests.conftest import eventually, make_harness, write_config

GB = 1000**3
START = datetime(2026, 10, 1, 12, 0)


class World:
    def __init__(self, tmp_path: Path, retention_days: int = 14) -> None:
        self.at = START
        db = Database(tmp_path / "ama.sqlite3")
        self.runs = Runs(db, EventBus(), now=self.now)
        self.jobs = JobStore(db, tmp_path / "scratch", now=self.now, runs=self.runs)
        self.movies = Movies(db, now=self.now)
        self.tv = TvTitles(db, now=self.now)
        self.days = retention_days
        self.sizes: dict[Path, int] = {}
        self.floor_gb = 0
        self.free = 256 * GB
        self.cleaner = ScratchCleaner(self.jobs, self.runs, lambda: self.days,
                                      floor_gb=lambda: self.floor_gb, free=lambda: self.free,
                                      now=self.now, size=lambda path: self.sizes[path])

    def now(self) -> datetime:
        return self.at

    def later(self, **delta) -> None:
        self.at += timedelta(**delta)

    def ripped(self, label: str, size: int = 2 * GB) -> int:
        job = self.jobs.create(DiscType.BD, label, "video")
        job.scratch_dir.mkdir(parents=True)
        (job.scratch_dir / "t00.mkv").write_bytes(b"rip")
        self.sizes[job.scratch_dir] = size
        self.jobs.mark_ripped(job.id)
        return job.id

    def film(self, label: str, status: EncodeStatus, size: int = 2 * GB) -> int:
        job_id = self.ripped(label, size)
        self.movies.enqueue(job_id, Candidate(1, label.title(), label.title(), 2016, "en", 120),
                            1)
        self.movies.set_status(job_id, status)
        if status == EncodeStatus.FAILED:
            self.jobs.encode_failed(job_id)
        return job_id

    def scratch(self, job_id: int) -> Path:
        return self.jobs.get(job_id).scratch_dir


def _steps(w: World) -> list[tuple[str, str]]:
    run = w.runs.list_runs([RunKind.SCRATCH])[0]
    return [(s.subject, s.result) for s in w.runs.steps(run.id)]


def test_a_failed_encode_older_than_the_retention_age_is_removed_and_logged(tmp_path):
    w = World(tmp_path)
    old = w.film("OLD_FILM", EncodeStatus.FAILED, size=3 * GB)
    w.later(days=15)
    w.cleaner.clean()
    assert not w.scratch(old).exists()
    rec = w.jobs.get(old)
    assert rec.status == JobStatus.FAILED and rec.failure.kind == FailureKind.SCRATCH_CLEANED
    assert rec.scratch_cleaned_at == w.at
    assert rec.dismissed
    [run] = w.runs.list_runs([RunKind.SCRATCH])
    assert run.failed is False and run.finished_at is not None
    assert _steps(w) == [("OLD_FILM (Job 1)", "3.0 GB · older than 14 days")]


def test_nothing_older_than_the_retention_age_means_no_run(tmp_path):
    w = World(tmp_path)
    young = w.film("YOUNG_FILM", EncodeStatus.FAILED)
    w.later(days=13)
    w.cleaner.clean()
    assert w.scratch(young).exists()
    assert w.runs.list_runs([RunKind.SCRATCH]) == []


def test_off_by_default_zero_days_removes_nothing(tmp_path):
    w = World(tmp_path, retention_days=0)
    old = w.film("OLD_FILM", EncodeStatus.FAILED)
    w.later(days=400)
    w.cleaner.clean()
    assert w.scratch(old).exists()
    assert w.runs.list_runs([RunKind.SCRATCH]) == []


def test_jobs_still_on_their_way_are_never_touched(tmp_path):
    w = World(tmp_path)
    ripping = w.jobs.create(DiscType.BD, "RIPPING", "video").id
    w.scratch(ripping).mkdir(parents=True)
    identifying = w.ripped("BEING_IDENTIFIED")
    review = w.ripped("IN_REVIEW")
    w.jobs.mark_review(review, ReviewReason.NO_MATCH)
    waiting = w.film("WAITING", EncodeStatus.QUEUED)
    encoding = w.film("ENCODING", EncodeStatus.ENCODING)
    encoded = w.film("ENCODED", EncodeStatus.ENCODED)
    tv = w.ripped("TV_HALF_DONE")
    series = Series(9, "Show", 2001, "en")
    w.tv.enqueue(tv, series, [(1, Episode(1, 1, "A"), PurePosixPath("TV/Show/a.mkv")),
                              (2, Episode(1, 2, "B"), PurePosixPath("TV/Show/b.mkv"))])
    w.tv.set_status(tv, 1, EncodeStatus.FAILED)
    w.later(days=100)
    w.cleaner.clean()
    for job_id in (ripping, identifying, review, waiting, encoding, encoded, tv):
        assert w.scratch(job_id).exists(), w.jobs.get(job_id).label
    assert w.runs.list_runs([RunKind.SCRATCH]) == []


def test_a_tv_job_whose_kept_titles_are_all_filed_or_failed_is_removed(tmp_path):
    w = World(tmp_path)
    tv = w.ripped("TV_DONE")
    w.tv.enqueue(tv, Series(9, "Show", 2001, "en"),
                 [(1, Episode(1, 1, "A"), PurePosixPath("TV/Show/a.mkv")),
                  (2, Episode(1, 2, "B"), PurePosixPath("TV/Show/b.mkv"))])
    w.tv.set_status(tv, 1, EncodeStatus.FILED)
    w.tv.set_status(tv, 2, EncodeStatus.FAILED)
    w.jobs.encode_failed(tv)
    w.later(days=15)
    w.cleaner.clean()
    assert not w.scratch(tv).exists()


def test_oldest_first_by_when_the_job_last_changed_status(tmp_path):
    w = World(tmp_path)
    first = w.film("FIRST_RIPPED", EncodeStatus.QUEUED)
    second = w.film("FAILED_FIRST", EncodeStatus.FAILED)
    w.later(days=1)
    w.movies.set_status(first, EncodeStatus.FAILED)
    w.jobs.encode_failed(first)
    w.later(days=20)
    w.cleaner.clean()
    assert [s for s, _ in _steps(w)] == [f"FAILED_FIRST (Job {second})",
                                         f"FIRST_RIPPED (Job {first})"]


def test_a_cleaned_job_is_not_queued_again_at_the_next_start(tmp_path):
    w = World(tmp_path)
    old = w.film("OLD_FILM", EncodeStatus.FAILED)
    w.later(days=15)
    w.cleaner.clean()
    assert w.movies.requeue_unfinished() == []
    assert w.movies.get(old).status == EncodeStatus.FAILED


def test_a_cleanup_cut_off_by_a_restart_finishes_on_the_next_start(tmp_path):
    w = World(tmp_path)
    old = w.film("OLD_FILM", EncodeStatus.FAILED)
    w.later(days=15)
    w.cleaner.claim()  # the Jobs are marked, then AMA stops before their files go
    assert w.scratch(old).exists()
    again = World(tmp_path)
    again.sizes = w.sizes
    again.at = w.at
    again.cleaner.clean()
    assert not again.scratch(old).exists()
    assert _steps(again) == [("OLD_FILM (Job 1)", "2.0 GB · finishing a cleanup cut off "
                                                  "by a restart")]
    again.cleaner.clean()
    assert len(again.runs.list_runs([RunKind.SCRATCH])) == 1


# --- the floor (#54) -------------------------------------------------------------------


def test_below_the_floor_the_oldest_kept_scratch_goes_until_free_space_is_above_it(tmp_path):
    w = World(tmp_path, retention_days=0)
    oldest = w.film("OLDEST", EncodeStatus.FAILED, size=10 * GB)
    w.later(hours=1)
    middle = w.film("MIDDLE", EncodeStatus.FAILED, size=10 * GB)
    w.later(hours=1)
    newest = w.film("NEWEST", EncodeStatus.FAILED, size=10 * GB)
    w.floor_gb, w.free = 20, 5 * GB
    w.cleaner.clean()
    assert not w.scratch(oldest).exists() and not w.scratch(middle).exists()
    assert w.scratch(newest).exists()
    assert _steps(w) == [(f"OLDEST (Job {oldest})", "10.0 GB · scratch below the 20 GB floor"),
                         (f"MIDDLE (Job {middle})", "10.0 GB · scratch below the 20 GB floor")]
    rec = w.jobs.get(oldest)
    assert rec.failure.kind == FailureKind.SCRATCH_CLEANED
    [run] = w.runs.list_runs([RunKind.SCRATCH])
    assert run.detail == "2 Jobs · 20.0 GB freed"


def test_the_floor_is_off_by_default(tmp_path):
    w = World(tmp_path, retention_days=0)
    kept = w.film("KEPT", EncodeStatus.FAILED)
    w.free = 0
    w.cleaner.clean()
    assert w.scratch(kept).exists()
    assert w.runs.list_runs([RunKind.SCRATCH]) == []


def test_above_the_floor_nothing_younger_than_the_retention_age_goes(tmp_path):
    w = World(tmp_path)
    kept = w.film("KEPT", EncodeStatus.FAILED)
    w.floor_gb, w.free = 20, 21 * GB
    w.cleaner.clean()
    assert w.scratch(kept).exists()
    assert w.runs.list_runs([RunKind.SCRATCH]) == []


def test_what_the_retention_age_removes_counts_toward_the_floor(tmp_path):
    w = World(tmp_path)
    old = w.film("OLD", EncodeStatus.FAILED, size=10 * GB)
    w.later(days=15)
    young = w.film("YOUNG", EncodeStatus.FAILED, size=10 * GB)
    w.floor_gb, w.free = 20, 15 * GB
    w.cleaner.clean()
    assert not w.scratch(old).exists() and w.scratch(young).exists()
    assert _steps(w) == [(f"OLD (Job {old})", "10.0 GB · older than 14 days")]


def test_still_below_the_floor_with_nothing_left_the_run_says_so(tmp_path):
    w = World(tmp_path, retention_days=0)
    only = w.film("ONLY", EncodeStatus.FAILED, size=2 * GB)
    on_its_way = w.film("ENCODING", EncodeStatus.ENCODING, size=30 * GB)
    w.floor_gb, w.free = 20, 5 * GB
    w.cleaner.clean()
    assert not w.scratch(only).exists() and w.scratch(on_its_way).exists()
    [run] = w.runs.list_runs([RunKind.SCRATCH])
    assert run.failed is False
    assert run.detail == ("1 Job · 2.0 GB freed · still below the 20 GB floor, "
                          "nothing else to remove")


# --- the app ---------------------------------------------------------------------------


def _text(page: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page)))


def _failed_encode(h, days_ago: int) -> int:
    """Rip a film whose Encode fails, then back-date its last change by `days_ago` days."""
    h.ffmpeg.exit_code = 1
    h.web.add_film("Example Movie", 1234, "Example Movie", runtime=122)
    finished = threading.Event()
    tell_cleaner = h.services.jobs.finished
    h.services.jobs.finished = lambda: (tell_cleaner(), finished.set())
    h.makemkv.release()
    h.drive.insert(DiscType.BD, "EXAMPLE_MOVIE")
    eventually(finished.is_set)
    assert h.services.movie_archive.movies.get(1).status == EncodeStatus.FAILED
    then = (datetime.now() - timedelta(days=days_ago)).isoformat(timespec="seconds")
    # Test setup only: no clock is injected into the app.
    h.services.db.execute("UPDATE jobs SET changed_at = ? WHERE id = 1", (then,))
    return 1


def test_saving_a_retention_age_removes_old_kept_scratch_at_once(tmp_path):
    toml = write_config(tmp_path)
    h = make_harness(tmp_path, config_file=toml)
    with TestClient(create_app(h.services)) as client:
        job = _failed_encode(h, days_ago=20)
        scratch = h.services.jobs.get(job).scratch_dir
        page = _text(client.get("/settings/general").text)
        assert "Scratch cleanup" in page and "Remove kept scratch after" in page
        assert h.services.config.scratch.retention_days == 0  # off by default
        assert scratch.exists()

        r = client.post("/settings/general", data={"scratch.retention_days": "14"},
                        follow_redirects=False)
        assert r.status_code == 303
        assert "retention_days = 14" in toml.read_text(encoding="utf-8")
        eventually(lambda: not scratch.exists())

        rec = h.services.jobs.get(job)
        assert rec.status == JobStatus.FAILED and rec.dismissed
        today = datetime.now()
        job_page = _text(client.get(f"/jobs/{job}").text)
        assert f"Scratch cleaned up {today.day} {today:%b %Y}" in job_page
        assert "The Encode didn't work" in job_page
        assert "retried when the app restarts" not in job_page

        [run] = h.services.runs.list_runs([RunKind.SCRATCH])
        assert "Cleaned up scratch" in _text(client.get("/logs?kind=app").text)
        run_page = client.get(f"/logs/runs/{run.id}").text
        assert "EXAMPLE_MOVIE (Job 1)" in _text(run_page)
        assert "older than 14 days" in _text(run_page)
        assert f'href="/jobs/{job}"' in run_page


def test_at_startup_old_kept_scratch_is_removed_before_its_encode_is_retried(tmp_path):
    toml = write_config(tmp_path)
    h = make_harness(tmp_path, config_file=toml)
    with TestClient(create_app(h.services)):
        _failed_encode(h, days_ago=8)
    scratch = h.services.jobs.get(1).scratch_dir
    assert scratch.exists()

    toml.write_text(toml.read_text(encoding="utf-8") + "\n[scratch]\nretention_days = 7\n",
                    encoding="utf-8")
    again = make_harness(tmp_path, config_file=toml)
    again.web.add_film("Example Movie", 1234, "Example Movie", runtime=122)
    with TestClient(create_app(again.services)):
        eventually(lambda: not scratch.exists())
    rec = again.services.jobs.get(1)
    assert rec.status == JobStatus.FAILED and rec.failure.kind == FailureKind.SCRATCH_CLEANED
    assert again.services.movie_archive.movies.get(1).status == EncodeStatus.FAILED
    assert again.ffmpeg.calls == []


def test_saving_a_floor_with_scratch_low_removes_kept_scratch_at_once(tmp_path):
    toml = write_config(tmp_path)
    h = make_harness(tmp_path, config_file=toml)
    with TestClient(create_app(h.services)) as client:
        job = _failed_encode(h, days_ago=0)
        scratch = h.services.jobs.get(job).scratch_dir
        page = _text(client.get("/settings/general").text)
        assert "Free scratch to keep" in page
        assert h.services.config.scratch.floor_gb == 0  # off by default
        h.disk.used = h.disk.total - 5 * GB

        r = client.post("/settings/general", data={"scratch.floor_gb": "20"},
                        follow_redirects=False)
        assert r.status_code == 303
        assert "floor_gb = 20" in toml.read_text(encoding="utf-8")
        eventually(lambda: not scratch.exists())
        [run] = h.services.runs.list_runs([RunKind.SCRATCH])
        assert "scratch below the 20 GB floor" in _text(client.get(f"/logs/runs/{run.id}").text)
