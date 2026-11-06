"""Skip a Title during the Rip (#56): untick a Title that hasn't started and it's never ripped."""

import html

from ama.drive import DiscType
from ama.jobs import JobStatus
from tests.conftest import eventually


def page_text(client, url: str) -> str:
    return html.unescape(client.get(url).text)


def _ripping_title_1(client, harness) -> None:
    harness.drive.insert(DiscType.BD, "EXAMPLE_MOVIE")
    eventually(lambda: "Title 1 of 2" in page_text(client, "/jobs/1"))


def _tick(client, number: int, rip: bool):
    return client.post(f"/jobs/1/titles/{number}", data={"rip": "1"} if rip else {})


def test_an_unticked_waiting_title_is_skipped_and_never_ripped(client, harness):
    _ripping_title_1(client, harness)

    assert _tick(client, 2, rip=False).status_code == 204
    harness.makemkv.release()
    eventually(lambda: harness.drive.ejected == 1)

    assert harness.makemkv.ripped_ids == [0]
    page = page_text(client, "/jobs/1")
    assert "Skipped by you" in page
    assert "Not ripped: Title 2 skipped by you and 12 Titles shorter than 30 seconds" in page
    assert "1 Title, " in page  # the Rip Step: what was ripped


def test_a_title_ripping_or_ripped_cant_be_unticked(client, harness):
    _ripping_title_1(client, harness)
    page = client.get("/jobs/1").text
    assert '<input type="checkbox" aria-label="Rip Title 1" checked disabled>' in page
    assert 'hx-post="/jobs/1/titles/2"' in page

    assert _tick(client, 1, rip=False).status_code == 409
    harness.makemkv.release()
    eventually(lambda: harness.drive.ejected == 1)
    assert harness.makemkv.ripped_ids == [0, 1]
    assert _tick(client, 2, rip=False).status_code == 409  # the Rip is over
    assert "Skipped by you" not in page_text(client, "/jobs/1")


def test_a_title_ticked_again_before_its_turn_is_ripped(client, harness):
    _ripping_title_1(client, harness)
    _tick(client, 2, rip=False)
    assert "Skipped by you" in page_text(client, "/jobs/1")

    assert _tick(client, 2, rip=True).status_code == 204
    harness.makemkv.release()
    eventually(lambda: harness.drive.ejected == 1)
    assert harness.makemkv.ripped_ids == [0, 1]


def test_progress_and_the_titles_to_rip_leave_skipped_titles_out(client, harness):
    _ripping_title_1(client, harness)
    ripper = harness.services.video_rip
    eventually(lambda: ripper.progress.title_fraction == 0.5)
    assert ripper.progress.pct < 50  # half of Title 1, and Title 2 still to come
    assert "2 Titles to rip" in page_text(client, "/jobs/1")

    _tick(client, 2, rip=False)
    eventually(lambda: ripper.progress.pct == 50)  # half of all there is to rip
    assert "1 Title to rip" in page_text(client, "/jobs/1")


def test_review_lists_a_skipped_title_with_the_reason_and_it_cant_be_assigned(client, harness):
    _ripping_title_1(client, harness)
    _tick(client, 2, rip=False)
    harness.makemkv.release()
    eventually(lambda: harness.services.jobs.list(JobStatus.REVIEW))

    page = page_text(client, "/review/1")
    assert "Skipped by you: Title 2." in page
    assert "/review/1/titles/2/" not in page


def test_skipping_every_title_files_the_job_with_nothing_in_it(client, harness, monkeypatch):
    jobs, ripper = harness.services.jobs, harness.services.video_rip
    set_titles = jobs.set_titles

    def untick_all_before_the_first_turn(job_id, titles, **kw):
        titles = list(titles)
        set_titles(job_id, titles, **kw)
        for t in titles:
            assert ripper.skip(job_id, t.number, skipped=True)
        harness.services.db.execute("UPDATE jobs SET changed_at = '2000-01-01T00:00:00' "
                                    "WHERE id = ?", (job_id,))  # test setup: an old change

    monkeypatch.setattr(jobs, "set_titles", untick_all_before_the_first_turn)
    harness.drive.insert(DiscType.BD, "EXAMPLE_MOVIE")
    eventually(lambda: harness.drive.ejected == 1)
    eventually(lambda: ripper.progress is None)

    assert harness.makemkv.ripped_ids == []
    rec = jobs.get(1)
    assert rec.status == JobStatus.ARCHIVED and rec.failure is None
    page = page_text(client, "/jobs/1")
    assert "All 2 Titles skipped by you." in page
    assert "Nothing to archive: every Title was skipped" in page
    assert "Archived to" not in page and "once it is identified" not in page
    assert "Couldn't rip" not in page_text(client, "/")
    assert not rec.scratch_dir.exists()
    changed_at, = harness.services.db.execute(
        "SELECT changed_at FROM jobs WHERE id = 1").fetchone()
    assert changed_at > "2000-01-01T00:00:00"  # archiving it is a status change


def test_skipping_every_title_sends_no_alert(tmp_path, monkeypatch):
    import time

    from fastapi.testclient import TestClient

    from ama.app import create_app
    from tests.conftest import make_harness

    h = make_harness(tmp_path, discord="https://discord.com/api/webhooks/1/t", ntfy_topic="t")
    jobs, ripper = h.services.jobs, h.services.video_rip
    set_titles = jobs.set_titles

    def untick_all_before_the_first_turn(job_id, titles, **kw):
        titles = list(titles)
        set_titles(job_id, titles, **kw)
        for t in titles:
            ripper.skip(job_id, t.number, skipped=True)

    monkeypatch.setattr(jobs, "set_titles", untick_all_before_the_first_turn)
    with TestClient(create_app(h.services)):
        h.drive.insert(DiscType.BD, "EXAMPLE_MOVIE")
        eventually(lambda: jobs.get(1) is not None and jobs.get(1).status == JobStatus.ARCHIVED)
        time.sleep(0.3)
        assert h.web.discord == [] and h.web.ntfy == []
