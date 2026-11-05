"""TV Episode mapping, end to end: the real app with fakes for ffmpeg, the NAS folder
and the web (TMDB, Plex).

The TV Disc is put straight into scratch as ripped (the fake makemkvcon only knows a
film's Blu-ray): "THE_OFFICE_S1_D2", a DVD with three episodes (Titles 1-3), a
"Play all" of them (Title 4) and a 3-minute extra (Title 5).
"""

from __future__ import annotations

import html

from ama.archive import extended_path
from ama.jobs import JobStatus, ReviewReason, TitleRecord, TitleStatus
from ama.drive import DiscType
from tests.conftest import eventually

LABEL = "THE_OFFICE_S1_D2"
OFFICE = 2996
SHOW = "TV/The Office (2001) {tmdb-2996}"
TITLES = [(1, 29 * 60 + 10, "1"), (2, 29 * 60 + 40, "2"), (3, 30 * 60 + 5, "3"),
          (4, 88 * 60 + 55, "1,2,3"), (5, 3 * 60, "7")]


def _tv_disc(harness, label: str = LABEL, titles=TITLES, disc_type=DiscType.DVD):
    jobs = harness.services.jobs
    rec = jobs.create(disc_type, label, "video")
    rec.scratch_dir.mkdir(parents=True)
    records = []
    for n, seconds, segments in titles:
        name = f"{label}_t{n - 1:02d}.mkv"
        (rec.scratch_dir / name).write_bytes(b"mkv")
        records.append(TitleRecord(n, n - 1, seconds, 1_000_000_000, 2, 1, segments, name,
                                   TitleStatus.RIPPED))
    jobs.set_titles(rec.id, records, 0, 0)
    jobs.mark_ripped(rec.id)
    return rec


def _the_office(harness) -> None:
    harness.web.add_series("THE OFFICE", OFFICE, "The Office", 2001, {
        1: [(1, "Downsize", 30), (2, "Work Experience", 29), (3, "The Quiz", 29),
            (4, "Training", 30), (5, "New Girl", 29), (6, "Judgement", 30)],
        2: [(1, "Merger", 29)],
        0: [(1, "Christmas Special (1)", 45), (2, "Christmas Special (2)", 45)]})


def _in_review(harness, rec):
    eventually(lambda: harness.services.jobs.get(rec.id).status == JobStatus.REVIEW, timeout=5)
    return harness.services.jobs.get(rec.id)


def _page(client, url: str) -> str:
    r = client.get(url)
    assert r.status_code == 200, r.text
    return html.unescape(r.text)


def test_a_tv_disc_always_goes_to_review_even_when_a_film_matches(harness, client):
    # A film whose name and runtime fit the Disc's longest Title (the Play all).
    harness.web.add_film("THE OFFICE S1", 555, "The Office S1", runtime=89)
    rec = _in_review(harness, _tv_disc(harness))
    assert rec.review_reason == ReviewReason.EPISODES
    assert harness.services.movie_archive.movies.get(rec.id) is None
    assert harness.ffmpeg.encodes() == []
    queue = _page(client, "/review")
    assert "Looks like TV episodes" in queue and "Match episodes" in queue


def _searched_films(harness) -> list[str]:
    return [r.url.params["query"] for r in harness.web.tmdb_requests
            if r.url.path == "/3/search/movie"]


def test_a_tv_disc_of_many_equal_length_episodes_is_tv_not_decoys(harness, client):
    episodes = [(n, 22 * 60, str(n)) for n in range(1, 11)]
    rec = _in_review(harness, _tv_disc(harness, "SPACED_D1", episodes))
    assert rec.review_reason == ReviewReason.EPISODES
    assert _searched_films(harness) == []
    log = "\n".join(map(str, harness.services.jobs.log_lines(rec.id)))
    assert "decoy" not in log


def test_a_films_two_cuts_are_identified_as_the_film_not_tv(harness, client):
    harness.web.add_film("BLADE RUNNER", 78, "Blade Runner", runtime=117, year=1982)
    cuts = [(1, 117 * 60, "1-20"), (2, 112 * 60, "1-18,21"), (3, 14 * 60, "30")]
    rec = _tv_disc(harness, "BLADE_RUNNER", cuts, DiscType.BD)
    eventually(lambda: harness.services.movie_archive.movies.get(rec.id) is not None, timeout=5)
    assert harness.services.jobs.get(rec.id).review_reason is None


def test_two_episode_length_titles_are_tv_only_when_tmdb_knows_the_series(harness, client):
    two = [(1, 44 * 60, "1"), (2, 46 * 60, "2")]
    harness.web.add_series("THE WIRE", 1438, "The Wire", 2002, {1: [(1, "The Target", 62)]})
    rec = _in_review(harness, _tv_disc(harness, "THE_WIRE_S1_D1", two))
    assert rec.review_reason == ReviewReason.EPISODES
    other = _in_review(harness, _tv_disc(harness, "LOST_FOOTAGE", two))
    assert other.review_reason != ReviewReason.EPISODES


def test_the_review_page_suggests_the_series_and_an_episode_for_each_title(harness, client):
    _the_office(harness)
    rec = _in_review(harness, _tv_disc(harness))
    eventually(lambda: len(harness.ffmpeg.thumbnails) == 15)  # 5 Titles x 10/50/90%
    page = _page(client, f"/review/{rec.id}")
    assert "Which episode is each Title?" in page
    assert "DVD labelled “THE_OFFICE_S1_D2” · 5 Titles ripped" in page
    assert "The Office (2001)" in page and f"{SHOW}/Season 01" in page
    assert '<option value="1" selected>Season 1</option>' in page
    assert '<option value="0">Specials (Season 00)</option>' in page
    # Episode-length Titles get the season's Episodes in order; the Play all is discarded,
    # the short one kept as an Extra.
    assert '<option value="S01E01" selected>S01E01 · Downsize' in page
    assert '<option value="S01E03" selected>S01E03 · The Quiz' in page
    assert '<option value="S00E02">S00E02 · Christmas Special (2) · 45 min</option>' in page
    assert "“Play all”" in page
    assert page.count('value="discard" selected') == 1
    assert page.count('value="extra" selected') == 1
    assert "1 h 29 m" in page and "29 min" in page
    for pct in (10, 50, 90):
        assert f"/review/{rec.id}/titles/4/frames/{pct}" in page

    season2 = _page(client, f"/review/{rec.id}?series={OFFICE}&season=2")
    assert f"{SHOW}/Season 02" in season2
    assert '<option value="S02E01" selected>S02E01 · Merger' in season2


def _filed_names(harness) -> list[str]:
    root = extended_path(harness.nas_root / SHOW)
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*.mkv"))


def test_mapped_titles_are_encoded_and_filed_with_plex_tv_naming(harness, client):
    _the_office(harness)
    rec = _in_review(harness, _tv_disc(harness))
    r = client.post(f"/review/{rec.id}/episodes", follow_redirects=False, data={
        "series": str(OFFICE), "season": "1",
        "t1": "S01E03", "t2": "S01E05", "t3": "S00E01", "t4": "discard", "t5": "extra"})
    assert r.status_code == 303 and r.headers["location"] == f"/review?done={rec.id}"

    filed = eventually(lambda: harness.services.jobs.get(rec.id).status == JobStatus.FILED,
                       timeout=10) or harness.services.jobs.get(rec.id)
    assert filed.title == "The Office (2001) · 3 Episodes"
    assert _filed_names(harness) == [
        "Other/THE_OFFICE_S1_D2 - Title 5.mkv",
        "Season 00/The Office - s00e01 - Christmas Special (1).mkv",
        "Season 01/The Office - s01e03 - The Quiz.mkv",
        "Season 01/The Office - s01e05 - New Girl.mkv"]
    root = extended_path(harness.nas_root / SHOW)
    assert (root / "Season 01/The Office - s01e03 - The Quiz.mkv").read_bytes() == \
        f"HEVC {LABEL}_t00.mkv".encode()  # Title 1
    assert len(harness.ffmpeg.encodes()) == 4  # the Play all is never encoded
    eventually(lambda: not rec.scratch_dir.exists())  # the Rip is gone (ADR-0002)
    log = "\n".join(map(str, harness.services.jobs.log_lines(rec.id)))
    assert "Review: The Office (2001) (TMDB 2996); Title 1 = S01E03" in log
    assert "Title 5 = Extra; 1 discarded" in log
    assert "Nothing needs you right now" in _page(client, "/review")
    assert "The Office (2001) · 3 Episodes" in _page(client, "/")  # History, on Now


def test_episodes_share_the_one_encoder_with_films_and_show_on_the_now_page(harness, client):
    _the_office(harness)
    harness.ffmpeg.hold = True
    rec = _in_review(harness, _tv_disc(harness))
    client.post(f"/review/{rec.id}/episodes", data={
        "series": str(OFFICE), "season": "1",
        "t1": "S01E01", "t2": "S01E02", "t3": "S01E03", "t4": "discard", "t5": "discard"})
    eventually(harness.ffmpeg.encoding.is_set)
    eventually(lambda: "40%" in html.unescape(client.get("/").text))
    now = html.unescape(client.get("/").text)
    assert "The Office - s01e01 - Downsize" in now and "The Office - s01e02 - Work Experience" in now

    harness.web.add_film("Example Movie", 1234, "Example Movie", runtime=122)
    harness.makemkv.release()
    harness.drive.insert(DiscType.BD, "EXAMPLE_MOVIE")  # a film rips and waits its turn
    eventually(lambda: harness.services.movie_archive.movies.get(rec.id + 1) is not None)
    assert len(harness.ffmpeg.encodes()) == 1

    harness.ffmpeg.release()
    eventually(lambda: len(harness.services.jobs.list(JobStatus.FILED)) == 2, timeout=10)
    assert len(harness.ffmpeg.encodes()) == 5  # 3 Episodes, the film and its Extra (#8)
    assert "TV · 3 Episodes" in html.unescape(client.get("/").text)  # History, on Now


def test_a_failed_episode_encode_keeps_the_rip_and_is_queued_again_at_restart(harness, client):
    _the_office(harness)
    harness.ffmpeg.exit_code = 1
    rec = _in_review(harness, _tv_disc(harness))
    client.post(f"/review/{rec.id}/episodes", data={
        "series": str(OFFICE), "season": "1",
        "t1": "S01E01", "t2": "discard", "t3": "discard", "t4": "discard", "t5": "discard"})
    titles = harness.services.tv_archive.titles
    eventually(lambda: titles.for_job(rec.id)[0].status == "failed")
    assert harness.services.jobs.get(rec.id).status == JobStatus.RIPPED
    assert (rec.scratch_dir / f"{LABEL}_t00.mkv").exists()

    harness.ffmpeg.exit_code = 0
    harness.services.tv_archive.recover()  # what the next start does
    eventually(lambda: harness.services.jobs.get(rec.id).status == JobStatus.FILED,
               timeout=10)


def test_a_mapping_is_checked_and_ignored_once_the_disc_has_left_review(harness, client):
    _the_office(harness)
    rec = _in_review(harness, _tv_disc(harness))
    base = {"series": str(OFFICE), "season": "1", "t4": "discard", "t5": "discard"}
    twice = client.post(f"/review/{rec.id}/episodes",
                        data=base | {"t1": "S01E04", "t2": "S01E04", "t3": "S01E06"})
    assert twice.status_code == 400
    assert "Titles 1 and 2 are both S01E04" in html.unescape(twice.text)
    assert '<option value="S01E06" selected>' in twice.text  # the choices are kept
    nothing = client.post(f"/review/{rec.id}/episodes",
                          data=base | {"t1": "extra", "t2": "discard", "t3": "discard"})
    assert nothing.status_code == 400 and "Map at least one Title" in nothing.text
    unknown = client.post(f"/review/{rec.id}/episodes",
                          data=base | {"t1": "S01E99", "t2": "discard", "t3": "discard"})
    assert unknown.status_code == 400
    assert not harness.services.tv_archive.titles.has(rec.id)

    ok = base | {"t1": "S01E01", "t2": "discard", "t3": "discard"}
    assert client.post(f"/review/{rec.id}/episodes", data=ok,
                       follow_redirects=False).status_code == 303
    again = client.post(f"/review/{rec.id}/episodes", follow_redirects=False,
                        data=ok | {"t1": "S01E02"})
    assert again.status_code == 303
    [only] = harness.services.tv_archive.titles.for_job(rec.id)
    assert only.episode.code == "S01E01"
    eventually(lambda: harness.services.jobs.get(rec.id).status == JobStatus.FILED,
               timeout=10)


def test_any_video_disc_in_review_can_be_marked_as_tv_and_back(harness, client):
    _the_office(harness)
    harness.web.add_film("Example Movie", 1234, "Example Movie", runtime=121)
    harness.web.add_film("Example Movie", 78, "Example Movie", runtime=122, year=2020)
    harness.makemkv.release()
    harness.drive.insert(DiscType.BD, "EXAMPLE_MOVIE")  # a film's Disc, two films fit
    eventually(lambda: harness.services.jobs.list(JobStatus.REVIEW), timeout=5)
    [rec] = harness.services.jobs.list(JobStatus.REVIEW)
    assert "It's TV episodes" in _page(client, f"/review/{rec.id}")
    r = client.post(f"/review/{rec.id}/kind", data={"kind": "tv"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/review/{rec.id}"
    page = _page(client, f"/review/{rec.id}?q=THE OFFICE")
    assert "Which episode is each Title?" in page and "The Office (2001)" in page
    client.post(f"/review/{rec.id}/kind", data={"kind": "film"})
    assert "Which film is on this Disc?" in _page(client, f"/review/{rec.id}")


def test_the_user_can_search_for_another_series(harness, client):
    _the_office(harness)
    harness.web.add_series("The Office US", 2316, "The Office", 2005, {1: [(1, "Pilot", 23)]})
    rec = _in_review(harness, _tv_disc(harness))
    page = _page(client, f"/review/{rec.id}?q=The Office US")
    assert f'href="/review/{rec.id}?series=2316"' in page and "The Office (2005)" in page
    assert "The TV database (TMDB) has no series called “Nope”" in _page(client, f"/review/{rec.id}?q=Nope")
    picked = _page(client, f"/review/{rec.id}?series=2316")
    assert "TV/The Office (2005) {tmdb-2316}/Season 01" in picked
    harness.web.tmdb_offline = True
    assert "Couldn't reach TMDB" in _page(client, f"/review/{rec.id}?series=2316")
