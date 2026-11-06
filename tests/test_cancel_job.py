"""Cancelling a Job in progress: while it rips (video or CD) or after, while it encodes."""

from __future__ import annotations

import asyncio
import html
from pathlib import Path

from ama.drive import DiscType
from ama.jobs import FailureKind, JobStatus, ReviewReason
from tests.conftest import eventually


def _page(client, url: str) -> str:
    return html.unescape(client.get(url).text)


def _log(harness, job_id: int) -> str:
    return "\n".join(map(str, harness.services.jobs.log_lines(job_id)))


def test_cancelling_a_video_rip_stops_makemkv_ejects_and_throws_the_rip_away(client, harness):
    harness.drive.insert(DiscType.DVD, "HEAT_DISC1")
    eventually(lambda: harness.makemkv.ripping)
    assert "Cancel this Job" in _page(client, "/jobs/1")

    r = client.post("/jobs/1/cancel", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/jobs/1"
    eventually(lambda: harness.drive.ejected == 1)
    rec = harness.services.jobs.get(1)
    assert rec.status == JobStatus.FAILED and rec.failure.kind == FailureKind.RIP_CANCELLED
    assert not rec.scratch_dir.exists()
    assert harness.makemkv.ripped_ids == []
    assert "You cancelled the Rip" in _page(client, "/jobs/1")


def test_only_the_rip_under_way_can_be_cancelled(harness):
    assert harness.services.video_rip.cancel(1) is False
    assert harness.services.cd.cancel(1) is False


def test_cancelling_a_cd_rip_stops_cyanrip_ejects_and_throws_the_rip_away(client, harness):
    harness.cyanrip.hold_at = 2
    harness.drive.insert(DiscType.CD, "KID_A")
    harness.cyanrip.wait_until_held()
    rec = harness.services.jobs.list(JobStatus.RIPPING)[0]
    assert "Cancel this Job" in _page(client, f"/jobs/{rec.id}")

    assert client.post(f"/jobs/{rec.id}/cancel", follow_redirects=False).status_code == 303
    harness.cyanrip.release()  # cyanrip's next line is where it is stopped
    eventually(lambda: harness.services.jobs.get(rec.id).status == JobStatus.FAILED)
    rec = harness.services.jobs.get(rec.id)
    assert rec.failure.kind == FailureKind.RIP_CANCELLED
    eventually(lambda: harness.drive.ejected == 1)
    assert not rec.scratch_dir.exists()
    eventually(lambda: harness.services.cd.current is None)


def _film_encoding(harness):
    harness.web.add_film("Example Movie", 1234, "Example Movie", runtime=122)
    harness.ffmpeg.hold = True
    harness.makemkv.release()
    harness.drive.insert(DiscType.BD, "EXAMPLE_MOVIE")
    eventually(lambda: harness.ffmpeg.encoding.is_set())
    return harness.services.jobs.get(1)


def test_cancelling_an_encoding_job_stops_ffmpeg_and_files_nothing(client, harness):
    rec = _film_encoding(harness)
    assert rec.status == JobStatus.RIPPED

    assert client.post("/jobs/1/cancel", follow_redirects=False).status_code == 303
    rec = harness.services.jobs.get(1)
    assert rec.status == JobStatus.FAILED and rec.failure.kind == FailureKind.CANCELLED
    eventually(lambda: not harness.services.movie_archive.encoder.encoding(1))
    assert not rec.scratch_dir.exists()
    assert "you cancelled the Job" in _log(harness, 1)
    assert not list((harness.libraries_root / "Movies").rglob("*.mkv"))
    # Off the Encode queue for good: nothing more of it is encoded.
    harness.ffmpeg.release()
    assert harness.services.movie_archive.movies.queue() == []


def test_a_cancelled_job_is_never_encoded_again(harness):
    jobs = harness.services.jobs
    rec = jobs.create(DiscType.BD, "GONE", "video")
    encoder = harness.services.movie_archive.encoder
    encoder.cancel(rec.id)
    title = object()  # never looked at: nothing runs
    out = asyncio.run(encoder.encode_title(rec, title, "Gone (2020)", "en",
                                           rec.scratch_dir / "encode.mkv",
                                           Path("ffmpeg"), Path("ffprobe")))
    assert out is None and harness.ffmpeg.calls == []


def test_a_job_in_review_or_filed_cant_be_cancelled(client, harness):
    jobs = harness.services.jobs
    rec = jobs.create(DiscType.BD, "IN_REVIEW", "video")
    jobs.mark_review(rec.id, ReviewReason.NO_MATCH)
    assert client.post(f"/jobs/{rec.id}/cancel").status_code == 409
    assert jobs.get(rec.id).status == JobStatus.REVIEW
    assert "Cancel this Job" not in _page(client, f"/jobs/{rec.id}")
    jobs.mark_filed_empty(rec.id)
    assert client.post(f"/jobs/{rec.id}/cancel").status_code == 409
