"""Movie Review, end to end: the real app with a fake drive, makemkvcon, ffmpeg, NAS
folder and web (TMDB, Plex).

The fake BD rips two Titles: Title 1 (2:01:33, the Main Feature) and Title 2 (0:02:31).
Two TMDB films called "Example Movie" fit its runtime, so it lands in Review.
"""

from __future__ import annotations

import html
from pathlib import Path

from ama.archive import extended_path
from ama.discs import DiscStatus, ReviewReason
from tests.conftest import eventually
from tests.test_movie_archive import _rip, _wait_for


def _ambiguous(harness):
    harness.web.add_film("Example Movie", 1234, "Example Movie", runtime=121,
                         director="Ann Example")
    harness.web.add_film("Example Movie", 77, "Example Movie", runtime=95, year=1987,
                         director="Bob Older")
    harness.web.add_film("Example Movie", 78, "Example Movie", runtime=122, year=2020)
    _rip(harness)
    rec = _wait_for(harness, DiscStatus.REVIEW)
    assert rec.review_reason == ReviewReason.MULTIPLE_MATCHES
    return rec


def _page(client, url: str) -> str:
    r = client.get(url)
    assert r.status_code == 200, r.text
    return html.unescape(r.text)


def test_thumbnails_are_taken_at_10_50_and_90_percent_of_each_title_awaiting_review(
        harness, client):
    rec = _ambiguous(harness)
    eventually(lambda: len(harness.ffmpeg.thumbnails) == 6)
    seeks = sorted((Path(c[c.index("-i") + 1]).name, float(c[c.index("-ss") + 1]))
                   for c in harness.ffmpeg.thumbnails)
    assert seeks == [("Example_Movie_t00.mkv", 729.3), ("Example_Movie_t00.mkv", 3646.5),
                     ("Example_Movie_t00.mkv", 6563.7), ("Example_Movie_t01.mkv", 15.1),
                     ("Example_Movie_t01.mkv", 75.5), ("Example_Movie_t01.mkv", 135.9)]
    assert harness.ffmpeg.encodes() == []  # nothing is Encoded before the decision

    page = _page(client, f"/review/{rec.id}")
    for n in (1, 2):
        for pct in (10, 50, 90):
            assert f'src="/review/{rec.id}/titles/{n}/frames/{pct}.jpg' in page
    img = client.get(f"/review/{rec.id}/titles/1/frames/50.jpg")
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg"
    assert img.content.startswith(b"\xff\xd8")
    assert client.get(f"/review/{rec.id}/titles/9/frames/50.jpg").status_code == 404


def test_the_review_page_offers_the_films_found_with_how_their_runtime_fits(harness, client):
    rec = _ambiguous(harness)
    page = _page(client, f"/review/{rec.id}")
    assert "Which film is on this Disc?" in page
    assert "Blu-ray labelled “EXAMPLE_MOVIE” · main Title runs 2 h 1 m" in page
    assert 'value="Example Movie"' in page  # the search box holds what was searched
    assert "Ann Example · 2 h 1 m · matches the Disc" in page
    assert "Bob Older · 1 h 35 m · 26 m shorter than the Disc" in page
    assert page.index("Example Movie (2016)") < page.index("Example Movie (2020)") \
        < page.index("Example Movie (1987)")  # films that fit first
    assert 'name="film" value="1234" checked' in page
    assert 'name="title" value="1" checked' in page  # the Main Feature by default
    assert "2 h 1 m 33 s · the longest, likely the film" in page and "2 m 31 s" in page
    assert "Movies/Example Movie (2016) {tmdb-1234}" in page  # where it will be filed


def test_the_user_can_search_tmdb_for_another_film(harness, client):
    rec = _ambiguous(harness)
    harness.web.add_film("Arrival", 329865, "Arrival", runtime=118, director="Denis Villeneuve")
    page = _page(client, f"/review/{rec.id}?q=Arrival")
    assert "Search results" in page and 'value="Arrival"' in page
    assert "Arrival (2016)" in page and "Denis Villeneuve" in page
    assert "Example Movie (1987)" not in page
    assert "TMDB has no film called “Nope”" in _page(client, f"/review/{rec.id}?q=Nope")
    harness.web.tmdb_offline = True
    assert "Couldn't reach TMDB" in _page(client, f"/review/{rec.id}?q=Arrival")

    # The "When you confirm" facts follow what's picked.
    harness.web.tmdb_offline = False
    facts = _page(client, f"/review/{rec.id}/decision?film=329865&title=2")
    assert "Arrival (2016)" in facts and "Title 2 · 2 m" in facts
    assert "Movies/Arrival (2016) {tmdb-329865}" in facts


def test_confirming_review_queues_the_encode_of_the_chosen_title_as_the_chosen_film(
        harness, client):
    rec = _ambiguous(harness)
    harness.web.add_film("Arrival", 329865, "Arrival", runtime=118)
    r = client.post(f"/review/{rec.id}/film", data={"film": "329865", "title": "2"},
                    follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/review"
    movie = harness.services.movie_archive.movies.get(rec.id)
    assert movie.film.name == "Arrival (2016)" and movie.title_number == 2

    filed = _wait_for(harness, DiscStatus.FILED)
    assert filed.title == "Arrival (2016)"
    folder = "Arrival (2016) {tmdb-329865}"
    path = extended_path(harness.nas_root / "Movies" / folder / f"{folder}.mkv")
    assert path.read_bytes() == b"HEVC Example_Movie_t01.mkv"  # the Title the user chose
    log = "\n".join(map(str, harness.services.discs.log_lines(rec.id)))
    assert "Review: identified as Arrival (2016)" in log
    assert "Nothing needs you right now" in _page(client, "/review")


def test_a_decision_is_ignored_once_the_disc_has_left_review_and_checked_otherwise(
        harness, client):
    rec = _ambiguous(harness)
    bad = client.post(f"/review/{rec.id}/film", data={"film": "1234", "title": "9"},
                      follow_redirects=False)
    assert bad.status_code == 400
    assert harness.services.movie_archive.movies.get(rec.id) is None

    ok = {"film": "1234", "title": "1"}
    assert client.post(f"/review/{rec.id}/film", data=ok, follow_redirects=False
                       ).status_code == 303
    again = client.post(f"/review/{rec.id}/film", data={"film": "77", "title": "2"},
                        follow_redirects=False)
    assert again.status_code == 303
    assert harness.services.movie_archive.movies.get(rec.id).film.id == 1234
    _wait_for(harness, DiscStatus.FILED)
    assert client.get(f"/review/{rec.id}", follow_redirects=False).status_code == 303
