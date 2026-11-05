"""A pick the user made while the Disc ripped is accepted like an automatic match when it
passes the same check (ADR 0005 otherwise): a film's TMDB runtime within the tolerance of
the Main Feature, a CD release that fits the Rip. A pick that fails goes to Review with
the pick pre-filled and the reason shown. TV Jobs always go to Review.

The fake DVD's Main Feature (Title 1) runs 2 h 1 m 33 s.
"""

from __future__ import annotations

import re
from html import unescape

from ama.drive import DiscType
from ama.jobs import JobStatus, ReviewReason, TitleRecord, TitleStatus
from tests.conftest import eventually
from tests.test_cd_guess import SPECIAL, STANDARD, _response, _rip_held, eventually_status
from tests.test_tv_review import LABEL, TITLES as TV_TITLES


def page_text(client, url: str) -> str:
    return unescape(client.get(url).text)


def _rip_picking(harness, client, film_id: int, label: str = "HEAT_DISC1") -> None:
    """Rip a DVD, picking `film_id` on the rip card while it rips."""
    harness.drive.insert(DiscType.DVD, label)
    eventually(lambda: "Title 1 of 2" in page_text(client, "/disc"))
    r = client.post("/jobs/1/guess", data={"film": str(film_id), "next": "/disc"},
                    follow_redirects=False)
    assert r.status_code == 303
    harness.makemkv.release()


def _log(harness, job_id: int = 1) -> str:
    return "\n".join(map(str, harness.services.jobs.log_lines(job_id)))


def test_a_picked_film_whose_runtime_matches_goes_straight_to_encoding(client, harness):
    harness.web.add_film("Heat", 949, "Heat", runtime=170, year=1995)  # the label's guess
    harness.web.add_film("Collateral", 1539, "Collateral", runtime=120, year=2004)
    _rip_picking(harness, client, 1539)

    rec = eventually_status(harness, JobStatus.FILED)
    assert rec.title == "Collateral (2004)"
    log = _log(harness)
    assert "Identified as Collateral (2004) (your pick" in log
    assert "Needs Review" not in log


def test_a_picked_film_whose_runtime_doesnt_match_goes_to_review_pre_filled_with_the_reason(
        client, harness):
    harness.web.add_film("Heat", 949, "Heat", runtime=170, year=1995)
    harness.web.add_film("Collateral", 1538, "Collateral", runtime=90, year=1999)
    _rip_picking(harness, client, 1538)

    rec = eventually_status(harness, JobStatus.REVIEW)
    assert rec.review_reason == ReviewReason.PICK_RUNTIME_MISMATCH
    assert harness.services.movie_archive.movies.get(rec.id) is None  # not queued for Encode
    queue = page_text(client, "/review")
    assert "The running time of the film you picked doesn't match the Disc" in queue
    review = client.get("/review/1").text
    assert 'value="1538" checked' in review  # the pick, pre-filled
    assert "The film you picked runs 1 h 30 m; the main Title runs 2 h 1 m" in unescape(review)
    assert "Picked while it ripped: Collateral (1999)" in _log(harness)


def test_a_tv_job_goes_to_review_even_with_a_picked_film_that_fits(client, harness):
    # The longest Title is the Play all (1 h 28 m 55 s); the picked "film" runs 89 min.
    harness.web.add_film("THE OFFICE S1", 555, "The Office S1", runtime=89)
    jobs = harness.services.jobs
    rec = jobs.create(DiscType.DVD, LABEL, "video")
    rec.scratch_dir.mkdir(parents=True)
    records = []
    for n, seconds, segments in TV_TITLES:
        name = f"{LABEL}_t{n - 1:02d}.mkv"
        (rec.scratch_dir / name).write_bytes(b"mkv")
        records.append(TitleRecord(n, n - 1, seconds, 1_000_000_000, 2, 1, segments, name,
                                   TitleStatus.RIPPED))
    jobs.set_titles(rec.id, records, 0, 0)
    harness.services.film_guesses.pick(rec.id, 555)
    jobs.mark_ripped(rec.id)

    rec = eventually_status(harness, JobStatus.REVIEW)
    assert rec.review_reason == ReviewReason.EPISODES
    assert harness.services.movie_archive.movies.get(rec.id) is None
