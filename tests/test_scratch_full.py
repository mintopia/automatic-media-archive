"""Full scratch: a Disc that wouldn't fit on scratch is ejected unripped, and the UI says why."""

from __future__ import annotations

import html

from ama.jobs import JobStatus
from ama.drive import DiscType
from tests.conftest import eventually

GB = 1000**3


def page_text(client, url: str) -> str:
    return html.unescape(client.get(url).text)


def test_blu_ray_is_ejected_unripped_when_scratch_is_below_its_threshold(client, harness):
    harness.disk.used = 212 * GB  # 44 GB free; a Blu-ray needs 50
    harness.drive.insert(DiscType.BD, "THE_MATRIX")
    eventually(lambda: harness.drive.ejected == 1)
    assert harness.makemkv.calls == []
    assert harness.services.jobs.get(1) is None
    page = page_text(client, "/scratch")
    assert "Ejected: not enough space" in page
    assert ("THE_MATRIX · Blu-ray was not ripped. 212 of 256 GB of scratch is in use; "
            "a Blu-ray needs up to 50 GB.") in page
    assert "Not enough space for “THE_MATRIX”" in page_text(client, "/")


def test_cd_is_ejected_unripped_when_scratch_is_full(client, harness):
    harness.disk.used = harness.disk.total - GB // 2
    harness.drive.insert(DiscType.CD, "OK_COMPUTER")
    eventually(lambda: harness.drive.ejected == 1)
    assert [c for c in harness.cyanrip.calls if "-I" not in c] == []
    assert harness.services.jobs.get(1) is None
    assert "an Audio CD needs up to 1 GB" in page_text(client, "/scratch")


def test_a_disc_that_fits_is_ripped_and_clears_the_refusal(client, harness):
    harness.disk.used = 212 * GB
    harness.drive.insert(DiscType.UHD, "BLADE_RUNNER")
    eventually(lambda: harness.drive.ejected == 1)
    harness.disk.used = 0
    harness.makemkv.release()
    harness.drive.insert(DiscType.DVD, "SPIRITED_AWAY")
    eventually(lambda: harness.drive.ejected == 2)
    assert harness.services.jobs.get(1).disc_type == DiscType.DVD
    assert "not enough space" not in page_text(client, "/scratch")
    assert "Not enough space" not in page_text(client, "/")


def test_scratch_page_lists_the_discs_holding_scratch(client, harness):
    harness.ffmpeg.hold = True
    harness.web.add_film("Example Movie", 1234, "Example Movie", runtime=122)
    harness.makemkv.release()
    harness.drive.insert(DiscType.BD, "EXAMPLE_MOVIE")  # Disc 1: Encoding
    eventually(harness.ffmpeg.encoding.is_set)
    harness.makemkv.disc_name = "Mystery Thing"
    harness.drive.insert(DiscType.BD, "MYSTERY_THING")  # Disc 2: no TMDB match -> Review
    eventually(lambda: harness.services.jobs.list(JobStatus.REVIEW))
    harness.cyanrip.hold_at = 2
    harness.drive.insert(DiscType.CD, "OK_COMPUTER")  # Disc 3: Ripping
    harness.cyanrip.wait_until_held()

    page = page_text(client, "/scratch")
    assert "Using scratch <span class=\"c\">3 GB</span>" in page
    rows = page.split('<div class="row">')[1:]
    assert len(rows) == 3
    ripping, review, encoding = rows
    assert "OK_COMPUTER" in ripping and "Ripping · " in ripping and "1 GB" in ripping
    assert "MYSTERY_THING" in review and "Needs Review · identify" in review
    assert 'href="/review/2"' in review
    assert "Example Movie (2016)" in encoding and "Encoding · 40%" in encoding
    assert "Not enough space" not in page and "Ejected" not in page
    assert 'href="/scratch"' in page_text(client, "/")  # the top-bar meter links here
    harness.cyanrip.release()
    harness.ffmpeg.release()


def test_meter_turns_full_when_a_disc_would_be_refused(client, harness):
    assert 'class="meter"' in page_text(client, "/")
    harness.disk.used = 200 * GB  # 56 GB free: a UHD Blu-ray (100 GB) wouldn't fit
    assert 'class="meter full"' in page_text(client, "/")


def test_a_refusal_is_pushed_live_to_the_scratch_page(live_server, harness):
    import httpx

    from tests.test_web_now import _read_event

    with httpx.stream("GET", f"{live_server}/events", timeout=5) as r:
        lines = r.iter_lines()
        assert "Ejected" not in _read_event(lines, "scratch")
        harness.disk.used = 250 * GB
        harness.drive.insert(DiscType.DVD, "SPIRITED_AWAY")
        while "Ejected: not enough space" not in html.unescape(_read_event(lines, "scratch")):
            pass
