"""Review, failure and History flows as a person sees them: guards before deleting,
what happens after a decision, and History saying what each Disc and Title became."""

from __future__ import annotations

import re

from ama.jobs import JobStatus
from ama.drive import DiscType
from tests.conftest import eventually
from tests.test_cd_archive import SPECIAL, _response
from tests.test_cd_review import _mismatch
from tests.test_movie_review import _ambiguous
from tests.test_sets import EPISODES, _file_first_office_disc, _file_example_movie, _filed
from tests.test_tv_review import OFFICE, _in_review, _page, _the_office, _tv_disc


def test_discarding_a_cd_rip_asks_first_then_says_what_happened(harness, client):
    rec = _mismatch(harness, _response(only=SPECIAL))

    page = _page(client, f"/review/{rec.id}")
    opener = page[page.index('id="discard-open"') - 60:page.index("Discard and re-rip")]
    assert 'type="button"' in opener and 'aria-controls="discard-confirm"' in opener
    start = page.index('id="discard-confirm"')
    dialog = page[start:page.index("</form>", start)]
    assert 'role="alertdialog"' in dialog and " hidden" in dialog
    assert f'action="/review/{rec.id}/discard"' in dialog and "Cancel" in dialog

    r = client.post(f"/review/{rec.id}/discard", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/review?done={rec.id}"
    after = _page(client, r.headers["location"])
    assert "Discarded the Rip of" in after and "Nothing was filed" in after
    assert "Discarded the Rip" not in _page(client, "/review")  # only right after


def test_a_decision_goes_on_to_the_next_disc_in_review_and_confirms_the_last(harness, client):
    _the_office(harness)
    first = _in_review(harness, _tv_disc(harness, "THE_OFFICE_S1_D1", EPISODES))
    second = _in_review(harness, _tv_disc(harness, "THE_OFFICE_S1_D2", EPISODES))

    r = client.post(f"/review/{first.id}/episodes", follow_redirects=False, data={
        "series": str(OFFICE), "season": "1", "t1": "S01E01", "t2": "S01E02", "t3": "S01E03"})
    assert r.headers["location"] == f"/review/{second.id}?done={first.id}"
    page = _page(client, r.headers["location"])
    assert "Done: The Office (2001) · 3 Episodes" in page
    assert "filed to TV" in page and "The next Disc that needs you is below." in page
    assert 'role="status"' in page


def test_a_failed_rip_offers_one_way_out(harness, client):
    harness.makemkv.fail_title = 1
    harness.makemkv.release()
    harness.drive.insert(DiscType.BD, "EXAMPLE_MOVIE")
    eventually(lambda: harness.drive.ejected == 1)
    eventually(lambda: harness.services.jobs.list(JobStatus.FAILED))
    rec = harness.services.jobs.list(JobStatus.FAILED)[0]
    page = _page(client, f"/jobs/{rec.id}")
    form = page[page.index(f'action="/jobs/{rec.id}/dismiss"'):]
    form = form[:form.index("</form>")]
    assert form.count("<button") == 1 and "OK, I'll put it back in" in form
    assert "Dismiss" not in page and "Try again" not in page


def test_a_filed_films_titles_say_what_each_became(harness, client):
    rec = _file_example_movie(harness)
    page = _page(client, f"/jobs/{rec.id}")
    titles = page[page.index('id="titles-h"') - 80:]
    titles = titles[:titles.index("</section>")]
    assert 'class="bin ink"' in titles and "Filed as" in titles
    assert "Main Feature" in titles
    assert "Ripped</span>" not in titles


def test_history_rows_show_set_position_and_no_filed_sticker(harness, client):
    _the_office(harness)
    _file_first_office_disc(harness, client)
    rec = _in_review(harness, _tv_disc(harness, "THE_OFFICE_S1_D2", EPISODES))
    client.post(f"/review/{rec.id}/set", data={"part": "yes", "set": f"tv:{OFFICE}:1",
                                                 "disc": "2"})
    client.post(f"/review/{rec.id}/episodes", data={
        "series": str(OFFICE), "season": "1", "t1": "S01E04", "t2": "S01E05", "t3": "S01E06"})
    _filed(harness, rec)

    history = _page(client, "/history")
    history = history[history.index("<main"):]
    assert "Disc 1 of 2" in history and "Disc 2 of 2" in history
    assert "stk fil" not in history
    for summary in re.findall(r"<summary.*?</summary>", history, re.S):
        assert "<a " not in summary


def test_movie_review_marks_and_choices(harness, client):
    rec = _ambiguous(harness)
    page = _page(client, f"/review/{rec.id}")
    assert "stk fil" not in page and 'class="mark"' in page  # "Same length" isn't a sticker
    assert '<div id="summary" aria-live="polite">' in page
    assert re.search(r'<button class="btn" type="submit" form="as-tv">It\'s TV episodes</button>',
                     page)
    row = page[page.index('class="title-row"'):]
    row = row[:row.index('class="shots"')]
    assert "frames" not in row  # the radio's label is the Title, not its pictures
    assert 'aria-labelledby="title-1-name"' in row
