"""The video Best guess: a film guessed while ripping, kept on the Job, changeable on the rip card."""

import html

import pytest

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
    assert "Best guess · " in client.get("/").text  # the Ripping bin's row
    harness.makemkv.release()
    eventually(lambda: in_review(harness))  # 170 min doesn't fit the 2 h Main Feature
    job = page_text(client, "/jobs/1")
    assert "Best guess" in job and "Heat (1995)" in job
    assert '<img src="/covers/tmdb-movie-949.jpg" alt="Poster of Heat (1995)">' in job
    assert "Best guess Heat (1995)" in page_text(client, "/review")  # its Review card
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
    harness.makemkv.release()  # what a pick does to Review: test_confirmed_pick.py


def test_the_best_guess_is_re_ranked_by_runtime_once_the_title_scan_has_the_longest_title(
        client, harness):
    harness.web.add_film("Heat", 949, "Heat", runtime=170, year=1995)  # TMDB's top result
    harness.web.add_film("Heat", 4413, "Heat", runtime=118, year=1986)
    harness.drive.insert(DiscType.DVD, "HEAT_DISC1")
    eventually(lambda: "Title 1 of 2" in page_text(client, "/disc"))
    eventually(lambda: "Heat (1986)" in page_text(client, "/disc"))  # the 2 h 1 m Title
    assert harness.services.film_guesses.get(1).film.id == 4413
    harness.makemkv.release()
    eventually(lambda: harness.drive.ejected == 1)


def test_without_a_tmdb_key_there_is_no_guess_and_no_error(tmp_path):
    from fastapi.testclient import TestClient

    from ama.app import create_app
    from tests.conftest import make_harness

    harness = make_harness(tmp_path, tmdb_key="")
    harness.web.add_film("Heat", 949, "Heat", runtime=121, year=1995)
    with TestClient(create_app(harness.services)) as client:
        harness.drive.insert(DiscType.DVD, "HEAT_DISC1")
        eventually(lambda: "Title 1 of 2" in page_text(client, "/disc"))
        page = page_text(client, "/disc")
        assert "Best guess" not in page and "Pick a title" not in page
        assert "guess-change" not in page and "TMDB" not in page
        assert "Searching needs a TMDB API key" in page_text(
            client, "/jobs/1/guess/search?q=Heat")
        harness.makemkv.release()
        eventually(lambda: harness.drive.ejected == 1)
        assert harness.services.film_guesses.get(1) is None
        assert "Best guess" not in page_text(client, "/jobs/1")
    assert not harness.web.tmdb_requests


@pytest.mark.parametrize("label",["DVD_VIDEO", "DISC1", "VIDEO_TS", "BDROM", "123456"])
def test_a_generic_volume_label_asks_the_user_to_pick_a_title(client, harness, label):
    harness.web.add_film("Video TS", 1, "Video TS", runtime=121, poster_path="/wrong.jpg")
    harness.web.add_film("Bdrom", 2, "Bdrom", runtime=121, poster_path="/wrong.jpg")
    harness.web.add_film("123456", 3, "123456", runtime=121, poster_path="/wrong.jpg")
    harness.drive.insert(DiscType.DVD, label)
    eventually(lambda: "Title 1 of 2" in page_text(client, "/disc"))
    eventually(lambda: "Pick a title" in page_text(client, "/disc"))
    for page in (page_text(client, "/disc"), page_text(client, "/")):
        assert "Best guess" not in page and "/covers/" not in page
    assert not harness.web.tmdb_requests
    harness.makemkv.release()
    eventually(lambda: harness.drive.ejected == 1)
