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


def test_the_user_can_search_tmdb_from_the_rip_card_and_pick_another_film(client, harness):
    harness.web.add_film("Heat", 949, "Heat", runtime=170, year=1995)
    harness.web.add_film("Collateral", 1538, "Collateral", runtime=90, year=1999)
    harness.web.add_film("Collateral", 1539, "Collateral", runtime=120, year=2004)
    harness.drive.insert(DiscType.DVD, "HEAT_DISC1")
    eventually(lambda: "Title 1 of 2" in page_text(client, "/disc"))
    assert 'id="guess-change-1"' in page_text(client, "/disc")
    results = page_text(client, "/jobs/1/guess/search?q=Collateral&next=/disc")
    # The longest Title is 2 h 1 m: the 2 h film first.
    assert results.index("Collateral (2004)") < results.index("Collateral (1999)")
    r = client.post("/jobs/1/guess", data={"film": "1539", "next": "/disc"},
                    follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/disc"
    guess = harness.services.film_guesses.get(1)
    assert guess is not None and guess.film.id == 1539 and guess.picked  # stored at once
    page = page_text(client, "/disc")
    assert "Collateral (2004)" in page and "your pick" in page
    harness.makemkv.release()
    eventually(lambda: in_review(harness))
    assert 'value="1539" checked' in client.get("/review/1").text
