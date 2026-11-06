"""The Job page (#41): one page per Job, the destination of every link to it, showing
each Step it has been through or still has to go through, live.

The real app with fakes. The fake BD (tests/data/makemkv-info-bd.txt) rips Title 1
(the Main Feature, 2:01:33) and Title 2 (an Extra, 2:31).
"""

from __future__ import annotations

import html

from ama.jobs import JobStatus
from ama.drive import DiscType
from tests.conftest import eventually


def _page(client, url: str) -> str:
    return html.unescape(client.get(url).text)


def _steps(page: str) -> str:
    """The Steps section of a Job page."""
    start = page.index('id="steps"')
    return page[start:page.index("</section>", start)]


def _crumb(page: str) -> str:
    crumb = page[page.index('class="crumb"'):]
    return crumb[:crumb.index("</div>")]


def _step(steps: str, name: str) -> str:
    """One Step's row, found by its name (and subject)."""
    rows = steps.split('class="step"')[1:]
    return next(r for r in rows if name in r)


def _encoding_film(client, harness):
    harness.ffmpeg.hold = True
    harness.web.add_film("Example Movie", 1234, "Example Movie", runtime=122)
    harness.makemkv.release()
    harness.drive.insert(DiscType.BD, "EXAMPLE_MOVIE")
    eventually(harness.ffmpeg.encoding.is_set)
    eventually(lambda: "40%" in _page(client, "/"))
    return harness.services.jobs.list(JobStatus.RIPPED)[0]


def test_the_encoding_row_opens_the_job_page_showing_the_encode_in_progress(client, harness):
    rec = _encoding_film(client, harness)
    now = _page(client, "/")
    encoding = now[now.index('id="encoding-h"'):]
    assert f'href="/jobs/{rec.id}"' in encoding[:encoding.index("</section>")]

    page = _page(client, f"/jobs/{rec.id}")
    steps = _steps(page)
    assert "st done" in _step(steps, ">Rip<")
    ident = _step(steps, "Identification")
    assert "st done" in ident and "Example Movie (2016)" in ident
    main = _step(steps, "Main Feature, Title 1")
    assert "st running" in main and "40%" in main and "2.0×" in main and "left" in main
    extra = _step(steps, "Extra, Title 2")
    assert "st waiting" in extra
    assert "st waiting" in _step(steps, ">Archive<")
    # It follows the pipeline live.
    assert 'hx-trigger="sse:encode' in page
    assert _steps(_page(client, f"/jobs/{rec.id}/steps")) == steps
    harness.ffmpeg.release()


def _card(page: str) -> str:
    """The Job page's drive card."""
    start = page.index('class="drive')
    return page[start:page.index('id="steps"')]


def test_a_job_encoding_shows_the_encoding_phase_not_ripping(client, harness):
    rec = _encoding_film(client, harness)
    card = _card(_page(client, f"/jobs/{rec.id}"))
    assert '<span class="stk enc">Encoding</span>' in card
    assert "Ripping" not in card and "Failed" not in card
    assert card.count("Best guess") <= 1
    harness.ffmpeg.release()


def test_a_ripping_job_before_any_progress_is_ripping_not_failed(client, harness):
    from ama.web import TEMPLATES, view_context
    harness.drive.insert(DiscType.BD, "EXAMPLE_MOVIE")
    eventually(lambda: harness.services.video_rip.active is not None)
    rec = harness.services.video_rip.active
    card = TEMPLATES.get_template("partials/rip_card.html").render(
        view_context(harness.services) | {"job": rec, "progress": None, "on_page": True})
    assert '<span class="stk rip">Ripping</span>' in card and "Failed" not in card
    harness.makemkv.release()


def test_the_crumb_follows_the_phase_and_review_and_history_link_to_the_job_page(
        client, harness):
    harness.web.add_film("Example Movie", 1234, "Example Movie", runtime=95)  # runtime is off
    harness.makemkv.release()
    harness.drive.insert(DiscType.BD, "EXAMPLE_MOVIE")
    eventually(lambda: harness.services.jobs.list(JobStatus.REVIEW), timeout=5)
    rec = harness.services.jobs.list(JobStatus.REVIEW)[0]

    for url in ("/", "/review"):  # the Review bin and the Review page
        assert f'href="/jobs/{rec.id}"' in _page(client, url)
    page = _page(client, f"/jobs/{rec.id}")
    assert '<a href="/review">Review</a>' in _crumb(page)
    assert '<a href="/review" aria-current="page">' in page
    ident = _step(_steps(page), "Identification")
    assert "st waiting" in ident and "Needs Review: Found in the film database" in ident
    assert "One per Title kept" in _step(_steps(page), ">Encode<")
    assert "To the Library, then a Plex scan" in _step(_steps(page), ">Archive<")

    client.post(f"/review/{rec.id}/film", data={"film": "1234", "title": "1"})
    eventually(lambda: harness.services.jobs.get(rec.id).status == JobStatus.ARCHIVED, timeout=5)
    assert f'href="/jobs/{rec.id}"' in _page(client, "/history")
    page = _page(client, f"/jobs/{rec.id}")
    assert '<a href="/history">History</a>' in _crumb(page)
    steps = _steps(page)
    assert steps.count('class="step') == 5 and steps.count("st done") == 5
    assert "Review: identified as Example Movie (2016)" in _step(steps, "Identification")
    assert "Extra: " in _step(steps, "Title 2") and " s<" in _step(steps, "Title 2")  # timed
    assert "Archived to Movies/Example Movie (2016) {tmdb-1234}" in _step(steps, ">Archive<")
    assert "waiting to be archived" not in steps


def test_the_rip_card_opens_the_job_page_live_while_it_rips(client, harness):
    harness.drive.insert(DiscType.BD, "EXAMPLE_MOVIE")  # the fake Rip holds at 50%
    eventually(lambda: harness.services.video_rip.active is not None)
    rec = harness.services.video_rip.active
    assert f'href="/jobs/{rec.id}"' in _page(client, "/")
    r = client.get("/disc", follow_redirects=False)
    assert r.headers["location"] == f"/jobs/{rec.id}"
    page = _page(client, f"/jobs/{rec.id}")
    assert 'sse-swap="rip"' in page and '<a href="/">Now</a>' in _crumb(page)
    steps = _steps(page)
    assert "st running rip" in _step(steps, ">Rip<")
    assert "st waiting" in _step(steps, "Identification")
    harness.makemkv.release()


def test_a_failed_rips_job_page_says_the_later_steps_wont_run(client, harness):
    harness.makemkv.fail_title = 1
    harness.makemkv.release()
    harness.drive.insert(DiscType.BD, "EXAMPLE_MOVIE")
    eventually(lambda: harness.services.jobs.list(JobStatus.FAILED))
    rec = harness.services.jobs.list(JobStatus.FAILED)[0]
    steps = _steps(_page(client, f"/jobs/{rec.id}"))
    assert "st failed" in _step(steps, ">Rip<") and "couldn't be ripped" in steps
    assert steps.count("st notrun") == 3  # Identification, Encode, File


def test_a_cds_job_page_has_no_encode(client, harness):
    from tests.test_history import ALBUM, _file_ffvii
    rec = _file_ffvii(harness)
    page = _page(client, f"/jobs/{rec.id}")
    steps = _steps(page)
    assert '<a href="/history">History</a>' in _crumb(page)
    assert ">Encode<" not in steps and steps.count("st done") == 3
    assert "24 tracks" in _step(steps, ">Rip<")
    assert ALBUM in _step(steps, "Identification")
    assert "MusicBrainz release" in _step(steps, "Identification")


def test_a_tv_jobs_page_lists_an_encode_per_episode(client, harness):
    from tests.test_tv_review import OFFICE, _in_review, _the_office, _tv_disc
    _the_office(harness)
    harness.ffmpeg.hold = True
    rec = _in_review(harness, _tv_disc(harness))
    client.post(f"/review/{rec.id}/episodes", data={
        "series": str(OFFICE), "season": "1", "t1": "S01E01", "t2": "S01E02", "t3": "S01E03",
        "t4": "discard", "t5": "extra"})
    eventually(harness.ffmpeg.encoding.is_set)
    eventually(lambda: "40%" in _steps(_page(client, f"/jobs/{rec.id}")))
    page = _page(client, f"/jobs/{rec.id}")
    steps = _steps(page)
    assert '<a href="/">Now</a>' in _crumb(page)
    assert "The Office (2001)" in _step(steps, "Identification")
    assert "st running" in _step(steps, "Episode S01E01 · Downsize, Title 1")
    assert "st waiting" in _step(steps, "Episode S01E03 · The Quiz, Title 3")
    assert "Title 5" in _step(steps, "Encode <span class=\"subj\">· Extra: ") and "Title 4" not in steps
    harness.ffmpeg.release()
    eventually(lambda: harness.services.jobs.get(rec.id).status == JobStatus.ARCHIVED, timeout=10)
    assert _steps(_page(client, f"/jobs/{rec.id}")).count("st done") == 7


def test_an_extras_discs_job_page_lists_its_extras(client, harness):
    from tests.test_sets import BONUS, _file_example_movie
    from tests.test_tv_review import _in_review, _tv_disc
    _file_example_movie(harness)
    rec = _in_review(harness, _tv_disc(harness, "EXAMPLE_MOVIE_BONUS", BONUS, DiscType.BD))
    client.post(f"/review/{rec.id}/set", data={"part": "yes", "set": "movie:1234", "disc": "2"})
    eventually(lambda: harness.services.jobs.get(rec.id).status == JobStatus.ARCHIVED, timeout=10)
    steps = _steps(_page(client, f"/jobs/{rec.id}"))
    assert "Extras of Example Movie (2016)" in _step(steps, "Identification")
    for n in (1, 2, 3):
        assert "st done" in _step(steps, f"Extra: EXAMPLE_MOVIE_BONUS - Title {n}<")


def _links_to_its_run(page: str, job_id: int) -> bool:
    crumb = _crumb(page)
    return f'<a class="view-log" href="/logs/jobs/{job_id}">' in crumb and "View log" in crumb


def test_a_job_page_links_to_its_run_while_it_rips_and_in_history(client, harness):
    harness.drive.insert(DiscType.BD, "EXAMPLE_MOVIE")  # the fake Rip holds at 50%
    eventually(lambda: harness.services.video_rip.active is not None)
    rec = harness.services.video_rip.active
    assert _links_to_its_run(_page(client, f"/jobs/{rec.id}"), rec.id)

    harness.web.add_film("Example Movie", 1234, "Example Movie", runtime=122)
    harness.makemkv.release()
    eventually(lambda: harness.services.jobs.list(JobStatus.ARCHIVED), timeout=5)
    page = _page(client, f"/jobs/{rec.id}")
    assert '<a href="/history">History</a>' in _crumb(page)
    assert _links_to_its_run(page, rec.id)


def test_a_failed_job_page_links_to_its_run_instead_of_embedding_the_log(client, harness):
    harness.makemkv.fail_title = 1
    harness.makemkv.release()
    harness.drive.insert(DiscType.BD, "EXAMPLE_MOVIE")
    eventually(lambda: harness.services.jobs.list(JobStatus.FAILED))
    rec = harness.services.jobs.list(JobStatus.FAILED)[0]
    page = _page(client, f"/jobs/{rec.id}")
    assert _links_to_its_run(page, rec.id)
    assert "full log" not in page and 'class="log"' not in page


def test_old_discs_urls_redirect_to_the_job_page(client):
    r = client.get("/discs/7/log", follow_redirects=False)
    assert r.status_code == 301 and r.headers["location"] == "/jobs/7/log"
