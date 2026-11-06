"""Video multi-disc sets (#14), end to end: the real app with fakes for ffmpeg, the Library
folder and the web (TMDB, Plex).

A later Disc of a set (the next Disc of a TV season, a film's Extras Disc) is attached
to the set in Review: it reuses the set's Identification and its Episodes/Extras go
into the set's existing Plex folder.
"""

from __future__ import annotations

import html

from ama.archive import extended_path
from ama.jobs import JobStatus
from ama.drive import DiscType
from tests.conftest import eventually
from tests.test_tv_review import OFFICE, SHOW, _in_review, _page, _the_office, _tv_disc

EPISODES = [(1, 29 * 60 + 10, "1"), (2, 29 * 60 + 40, "2"), (3, 30 * 60 + 5, "3")]


def _filed(harness, rec):
    eventually(lambda: harness.services.jobs.get(rec.id).status == JobStatus.FILED,
               timeout=10)
    return harness.services.jobs.get(rec.id)


def _file_first_office_disc(harness, client):
    rec = _in_review(harness, _tv_disc(harness, "THE_OFFICE_S1_D1", EPISODES))
    client.post(f"/review/{rec.id}/episodes", data={
        "series": str(OFFICE), "season": "1", "t1": "S01E01", "t2": "S01E02", "t3": "S01E03"})
    return _filed(harness, rec)


def _season_files(harness) -> list[str]:
    root = extended_path(harness.libraries_root / SHOW / "Season 01")
    return sorted(p.name for p in root.glob("*.mkv"))


def test_the_next_tv_disc_is_attached_to_its_set_and_continues_the_episodes(harness, client):
    _the_office(harness)
    _file_first_office_disc(harness, client)
    rec = _in_review(harness, _tv_disc(harness, "THE_OFFICE_S1_D2", EPISODES))

    asked = _page(client, f"/review/{rec.id}")
    assert "Is this Disc part of a set?" in asked
    assert "Part of an existing set" in asked
    assert "The Office (2001) · Season 1" in asked
    assert "Disc 1 filed · TV / The Office (2001) {tmdb-2996} / Season 01" in asked
    assert 'name="disc" type="number" min="1" value="2"' in asked
    assert "Not part of a set" in asked

    r = client.post(f"/review/{rec.id}/set", follow_redirects=False,
                    data={"part": "yes", "set": f"tv:{OFFICE}:1", "disc": "2"})
    assert r.status_code == 303 and r.headers["location"] == f"/review/{rec.id}"

    mapping = _page(client, f"/review/{rec.id}")
    assert "Which episode is each Title?" in mapping
    assert f"{SHOW}/Season 01" in mapping
    # Disc 1 had Episodes 1-3, so this Disc carries on from Episode 4.
    assert '<option value="S01E04" selected>S01E04 · Training' in mapping
    assert '<option value="S01E06" selected>S01E06 · Judgement' in mapping

    client.post(f"/review/{rec.id}/episodes", data={
        "series": str(OFFICE), "season": "1", "t1": "S01E04", "t2": "S01E05", "t3": "S01E06"})
    _filed(harness, rec)
    assert _season_files(harness) == [
        "The Office - s01e01 - Downsize.mkv", "The Office - s01e02 - Work Experience.mkv",
        "The Office - s01e03 - The Quiz.mkv", "The Office - s01e04 - Training.mkv",
        "The Office - s01e05 - New Girl.mkv", "The Office - s01e06 - Judgement.mkv"]

    third = _in_review(harness, _tv_disc(harness, "THE_OFFICE_S1_D3", EPISODES))
    asked = _page(client, f"/review/{third.id}")
    assert "Discs 1–2 filed" in asked and 'value="3"' in asked


FILM = "Movies/Example Movie (2016) {tmdb-1234}"
BONUS = [(1, 20 * 60, "1"), (2, 8 * 60, "2"), (3, 3 * 60, "3")]


def _file_example_movie(harness):
    harness.web.add_film("Example Movie", 1234, "Example Movie", runtime=122)
    harness.makemkv.release()
    harness.drive.insert(DiscType.BD, "EXAMPLE_MOVIE")
    eventually(lambda: harness.services.jobs.list(JobStatus.FILED), timeout=10)
    return harness.services.jobs.list(JobStatus.FILED)[0]


def test_an_extras_disc_files_its_titles_as_extras_in_the_films_folder(harness, client):
    _file_example_movie(harness)
    rec = _in_review(harness, _tv_disc(harness, "EXAMPLE_MOVIE_BONUS", BONUS, DiscType.BD))

    asked = _page(client, f"/review/{rec.id}")
    assert "Is this Disc part of a set?" in asked
    assert "Blu-ray labelled “EXAMPLE_MOVIE_BONUS” · BD · 3 Titles ripped" in asked
    assert "Extras Disc for a film already filed" in asked
    assert "Example Movie (2016)" in asked
    assert "Disc 1 filed · Movies / Example Movie (2016) {tmdb-1234}" in asked
    assert "Movies / Example Movie (2016) {tmdb-1234} / Other" in asked  # Where it goes
    assert 'value="2"' in asked

    r = client.post(f"/review/{rec.id}/set", follow_redirects=False,
                    data={"part": "yes", "set": "movie:1234", "disc": "2"})
    assert r.status_code == 303 and r.headers["location"] == f"/review?done={rec.id}"
    filed = _filed(harness, rec)
    assert filed.title == "Example Movie (2016) · 3 Extras"
    root = extended_path(harness.libraries_root / FILM)
    files = {p.relative_to(root).as_posix() for p in root.rglob("*.mkv")}
    assert "Example Movie (2016) {tmdb-1234} - 1080p.mkv" in files  # Disc 1, untouched
    assert {f for f in files if "BONUS" in f} == {
        "Other/EXAMPLE_MOVIE_BONUS - Title 1.mkv",
        "Other/EXAMPLE_MOVIE_BONUS - Title 2.mkv",
        "Other/EXAMPLE_MOVIE_BONUS - Title 3.mkv"}
    assert harness.services.movie_archive.movies.get(rec.id) is None  # not a film of its own
    def scans():  # Plex is asked just after the Disc is marked filed
        return [r.url.query for r in harness.web.plex_requests if "/refresh" in r.url.path]
    eventually(lambda: len(scans()) == 2)
    assert scans()[0] == scans()[1]  # the film's folder, both times
    now = _page(client, "/")
    assert "Example Movie (2016) · 3 Extras" in now and "Movies · 3 Extras" in now

    again = _in_review(harness, _tv_disc(harness, "EXAMPLE_MOVIE_BONUS_2", BONUS, DiscType.BD))
    assert "Discs 1–2 filed" in _page(client, f"/review/{again.id}")


def test_an_extras_disc_joins_its_film_where_it_was_filed_whatever_the_pattern_is_now(
        harness, client):
    harness.films_pattern("{year}/{title}/{title} - {version}")
    _file_example_movie(harness)
    harness.films_pattern("{title} ({year})/{title} - {version}")  # changed since
    rec = _in_review(harness, _tv_disc(harness, "EXAMPLE_MOVIE_BONUS", BONUS, DiscType.BD))

    assert "Disc 1 filed · Movies / 2016 / Example Movie" in _page(client, f"/review/{rec.id}")
    client.post(f"/review/{rec.id}/set", data={"part": "yes", "set": "movie:1234", "disc": "2"})
    filed = _filed(harness, rec)
    folder = harness.libraries_root / "Movies" / "2016" / "Example Movie"
    assert filed.archive_dir == folder
    assert sorted(p.relative_to(extended_path(folder)).as_posix()
                  for p in extended_path(folder).rglob("*.mkv")) == [
        "Example Movie - 1080p.mkv", "Other/EXAMPLE_MOVIE - Title 2.mkv",
        "Other/EXAMPLE_MOVIE_BONUS - Title 1.mkv", "Other/EXAMPLE_MOVIE_BONUS - Title 2.mkv",
        "Other/EXAMPLE_MOVIE_BONUS - Title 3.mkv"]
    assert not extended_path(harness.libraries_root / "Movies" / "Example Movie (2016)").exists()


def test_a_disc_not_part_of_a_set_is_identified_on_its_own_and_not_asked_again(harness, client):
    _the_office(harness)
    _file_first_office_disc(harness, client)
    rec = _in_review(harness, _tv_disc(harness, "THE_OFFICE_S1_D2", EPISODES))
    r = client.post(f"/review/{rec.id}/set", follow_redirects=False, data={"part": "no"})
    assert r.status_code == 303 and r.headers["location"] == f"/review/{rec.id}"
    page = _page(client, f"/review/{rec.id}")
    assert "Which episode is each Title?" in page
    # Even on its own, the series' later Disc carries on after the Episodes filed.
    assert '<option value="S01E04" selected>' in page
    assert f'href="/review/{rec.id}/set"' in page  # changed your mind?
    asked = _page(client, f"/review/{rec.id}/set")
    assert "Is this Disc part of a set?" in asked
    assert 'name="part" value="no" checked' in asked


def test_a_disc_named_like_no_filed_set_goes_straight_to_its_review(harness, client):
    _the_office(harness)
    _file_first_office_disc(harness, client)
    harness.web.add_series("FAWLTY TOWERS", 2207, "Fawlty Towers", 1975,
                           {1: [(1, "A Touch of Class", 30)]})
    rec = _in_review(harness, _tv_disc(harness, "FAWLTY_TOWERS_D1", EPISODES))
    page = _page(client, f"/review/{rec.id}")
    assert "Which episode is each Title?" in page and "Fawlty Towers" in page
    # Asked for, every filed set of its kind is offered.
    asked = _page(client, f"/review/{rec.id}/set")
    assert "The Office (2001) · Season 1" in asked
    assert "Extras Disc" not in asked


def test_a_set_answer_is_checked(harness, client):
    _the_office(harness)
    _file_first_office_disc(harness, client)
    rec = _in_review(harness, _tv_disc(harness, "THE_OFFICE_S1_D2", EPISODES))
    taken = client.post(f"/review/{rec.id}/set",
                        data={"part": "yes", "set": f"tv:{OFFICE}:1", "disc": "1"})
    assert taken.status_code == 400
    assert "Disc 1 of The Office (2001) · Season 1 is already filed" in html.unescape(taken.text)
    unknown = client.post(f"/review/{rec.id}/set",
                          data={"part": "yes", "set": "movie:1234", "disc": "2"})
    assert unknown.status_code == 400 and "Pick the set" in unknown.text
    assert "Is this Disc part of a set?" in _page(client, f"/review/{rec.id}")  # still asked
