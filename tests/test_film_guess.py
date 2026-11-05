"""The video Best guess: a film guessed while ripping, kept on the Job, changeable on the rip card."""

import html

from ama.drive import DiscType
from ama.jobs import JobStatus
from tests.conftest import eventually


def page_text(client, url: str) -> str:
    return html.unescape(client.get(url).text)


def in_review(harness) -> bool:
    return bool(harness.services.jobs.list(JobStatus.REVIEW))


def test_the_best_guess_is_kept_on_the_job_after_the_rip(client, harness):
    harness.web.add_film("Heat", 949, "Heat", runtime=170, year=1995, poster_path="/heat.jpg")
    harness.web.tmdb_images["/heat.jpg"] = b"\xff\xd8 heat poster"
    harness.drive.insert(DiscType.DVD, "HEAT_DISC1")
    eventually(lambda: "Heat (1995)" in page_text(client, "/disc"))
    harness.makemkv.release()
    eventually(lambda: in_review(harness))  # 170 min doesn't fit the 2 h Main Feature
    job = page_text(client, "/jobs/1")
    assert "Best guess" in job and "Heat (1995)" in job
    assert '<img src="/covers/tmdb-movie-949.jpg" alt="Poster of Heat (1995)">' in job
    assert "Best guess" in page_text(client, "/review/1")
