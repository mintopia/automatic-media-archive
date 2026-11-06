"""The TV Best guess: marked TV while it rips, the Disc's series is guessed, changeable on the
rip card, and TV Review starts from it."""

import html

from ama.drive import DiscType
from ama.jobs import JobStatus
from tests.conftest import eventually


def page_text(client, url: str) -> str:
    return html.unescape(client.get(url).text)


def _firefly(harness) -> None:
    harness.web.add_series("Firefly", 1437, "Firefly", 2002,
                           {1: [(n, f"Episode {n}", 44) for n in range(1, 15)]})
    harness.web.add_series("Serenity", 999, "Serenity Tales", 2010, {1: [(1, "One", 44)]})


def test_marking_a_disc_tv_while_it_rips_guesses_its_series(client, harness):
    _firefly(harness)
    harness.drive.insert(DiscType.DVD, "FIREFLY_DISC1")
    eventually(lambda: "Title 1 of 2" in page_text(client, "/disc"))
    assert "It's TV, not a film" in page_text(client, "/jobs/1")
    r = client.post("/jobs/1/kind", data={"kind": "tv", "next": "/jobs/1"},
                    follow_redirects=False)
    assert r.status_code == 303
    eventually(lambda: harness.services.series_guesses.get(1) is not None)
    page = page_text(client, "/jobs/1")
    assert "Firefly (2002)" in page and "TV, best guess" in page
    assert "Change the show" in page and "It's a film, not TV" in page
    harness.makemkv.release()
    eventually(lambda: bool(harness.services.jobs.list(JobStatus.REVIEW)))
    assert "TV/Firefly (2002) {tmdb-1437}/Season 01" in page_text(client, "/review/1")
    assert "Best guess Firefly (2002)" in page_text(client, "/review")


def test_the_user_can_search_tmdb_from_the_tv_rip_card_and_pick_another_series(client, harness):
    _firefly(harness)
    harness.drive.insert(DiscType.DVD, "FIREFLY_DISC1")
    eventually(lambda: "Title 1 of 2" in page_text(client, "/disc"))
    client.post("/jobs/1/kind", data={"kind": "tv"}, follow_redirects=False)
    assert "Serenity Tales (2010)" in page_text(client, "/jobs/1/series/search?q=Serenity")
    r = client.post("/jobs/1/series", data={"series": "999", "next": "/disc"},
                    follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/disc"
    guess = harness.services.series_guesses.get(1)
    assert guess is not None and guess.series.id == 999 and guess.picked
    harness.services.series_guesses.guess(harness.services.jobs.get(1))  # never replaces a pick
    assert harness.services.series_guesses.get(1).series.id == 999
    assert "your pick" in page_text(client, "/jobs/1")
    harness.makemkv.release()
    eventually(lambda: bool(harness.services.jobs.list(JobStatus.REVIEW)))
    assert "TV/Serenity Tales (2010) {tmdb-999}/Season 01" in page_text(client, "/review/1")


def test_a_generic_label_guesses_no_series(client, harness):
    harness.web.add_series("DVD VIDEO", 5, "DVD Video Show", 2001, {1: [(1, "One", 44)]})
    harness.drive.insert(DiscType.DVD, "DVD_VIDEO")
    eventually(lambda: "Title 1 of 2" in page_text(client, "/disc"))
    client.post("/jobs/1/kind", data={"kind": "tv"}, follow_redirects=False)
    assert harness.services.series_guesses.get(1) is None
    assert "Search for the show" in page_text(client, "/jobs/1")
    harness.makemkv.release()
