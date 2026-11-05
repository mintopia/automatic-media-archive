"""Decoy playlist detection (#9) on Title lists as the Rip records them."""

from __future__ import annotations

import html

from ama import decoys, makemkv
from ama.jobs import JobStatus, ReviewReason, TitleRecord
from ama.video_rip import MIN_TITLE_SECONDS, title_records
from tests.conftest import eventually
from tests.fakes import DATA
from tests.test_movie_archive import _rip


def _titles(fixture: str) -> list[TitleRecord]:
    scan = makemkv.parse_scan((DATA / fixture).read_text(encoding="utf-8").splitlines())
    return title_records(makemkv.select_titles(scan.titles, MIN_TITLE_SECONDS).keep)


def _t(number: int, duration_s: int, segments: str = "") -> TitleRecord:
    return TitleRecord(number=number, makemkv_id=number - 1, duration_s=duration_s,
                       size_bytes=duration_s * 4_000_000, audio=1, subtitles=1,
                       segments=segments, file=f"t{number:02d}.mkv")


def test_many_near_identical_titles_are_suspected_decoys_and_the_in_order_one_is_picked():
    found = decoys.detect(_titles("makemkv-info-bd-decoys.txt"))
    assert found is not None
    assert [t.number for t in found.versions] == list(range(1, 15))  # not the 2 extras
    assert found.likely.number == 6 and found.likely.source == "00805.mpls"  # segments 1-12
    assert found.confident


def test_a_normal_disc_has_no_decoys():
    assert decoys.detect(_titles("makemkv-info-bd.txt")) is None


def test_a_few_versions_of_the_film_or_a_set_of_episodes_are_not_decoys():
    film_cuts = [_t(1, 7293), _t(2, 7293), _t(3, 7294), _t(4, 900)]
    assert decoys.detect(film_cuts) is None
    episodes = [_t(n, 1300 + 23 * n) for n in range(1, 13)]  # 22-26 min, all different
    assert decoys.detect(episodes) is None
    trailers = [_t(n, 125) for n in range(1, 11)]  # short loops aren't a film
    assert decoys.detect(trailers) is None


def test_equal_length_episodes_are_not_decoys():
    episodes = [_t(n, 22 * 60, str(n)) for n in range(1, 11)]  # a TV Disc, timed to the second
    assert decoys.detect(episodes) is None
    long_episodes = [_t(n, 75 * 60, str(n)) for n in range(1, 9)]  # distinct clips
    assert decoys.detect(long_episodes) is None


def test_without_segment_order_to_go_on_the_pick_is_not_confident():
    same = [_t(n, 10_000 + n % 3) for n in range(1, 10)]
    found = decoys.detect(same)
    assert found is not None and len(found.versions) == 9
    assert found.likely.number == 1 and not found.confident


def _heat(harness):
    """A BD of Heat with 14 decoy playlists that TMDB identifies confidently."""
    harness.makemkv.scan_file = "makemkv-info-bd-decoys.txt"
    harness.web.add_film("Heat", 949, "Heat", runtime=170, year=1995, director="Michael Mann")
    _rip(harness, label="HEAT_BD")
    eventually(lambda: harness.services.jobs.list(JobStatus.REVIEW), timeout=10)
    return harness.services.jobs.list(JobStatus.REVIEW)[0]


def test_a_disc_with_decoys_goes_to_review_even_when_tmdb_is_confident(harness, client):
    rec = _heat(harness)
    assert rec.review_reason == ReviewReason.DECOY_PLAYLISTS
    assert harness.services.movie_archive.movies.get(rec.id) is None
    assert harness.ffmpeg.encodes() == []
    log = "\n".join(map(str, harness.services.jobs.log_lines(rec.id)))
    assert "Suspected decoy playlists: 14 Titles run within 3 s of each other" in log
    assert "Title 6 (00805.mpls) plays in order" in log
    row = html.unescape(client.get("/review").text)
    assert "14 near-identical versions of the film (a copy-protection trick)" in row


def test_the_review_page_warns_of_decoys_and_picks_the_version_that_plays_in_order(
        harness, client):
    rec = _heat(harness)
    page = html.unescape(client.get(f"/review/{rec.id}").text)
    assert "This Disc has 14 near-identical versions of the film" in page
    assert "Only one plays in the right order. We've picked the most likely one." in page
    assert 'name="film" value="949" checked' in page  # TMDB's match still offered first
    assert 'name="title" value="6" checked' in page
    assert "Title 6 · 00805.mpls" in page and "2 h 50 m 14 s · likely the film" in page
    assert page.count("scenes out of order") == 13
    assert "the longest, likely the film" not in page
    assert "Show 11 more versions and 2 other Titles" in page
    assert page.index("Title 6 · 00805.mpls") < page.index("Title 1 · 00800.mpls") \
        < page.index("Title 15</div>")  # the film, the other versions, then the rest
    assert "Title 6 · 2 h 50 m" in page  # When you confirm

    r = client.post(f"/review/{rec.id}/film", data={"film": "949", "title": "6"},
                    follow_redirects=False)
    assert r.status_code == 303
    assert harness.services.movie_archive.movies.get(rec.id).title_number == 6


def test_a_normal_review_page_has_no_decoy_notice(harness, client):
    harness.web.add_film("Example Movie", 1, "Example Movie", runtime=95)
    _rip(harness)
    eventually(lambda: harness.services.jobs.list(JobStatus.REVIEW), timeout=10)
    rec = harness.services.jobs.list(JobStatus.REVIEW)[0]
    page = html.unescape(client.get(f"/review/{rec.id}").text)
    assert "near-identical" not in page and "00800.mpls" not in page
    assert "the longest, likely the film" in page


def test_segment_maps_are_read_with_ranges():
    assert decoys.segments("1-3,7,5-6") == (1, 2, 3, 7, 5, 6)
    assert decoys.segments("") == () and decoys.segments("x") == ()
