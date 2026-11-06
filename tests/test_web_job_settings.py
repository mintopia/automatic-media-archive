"""The per-Job settings panel on the rip card and the Job page (#30)."""

from __future__ import annotations

import html
import re

from ama.drive import DiscType
from ama.jobs import JobStatus
from tests.conftest import eventually

HX = {"HX-Request": "true"}


def _text(r) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", r.text)).split())


def _ripping_bd(harness):
    harness.drive.insert(DiscType.BD, "EXAMPLE_MOVIE")
    eventually(lambda: harness.services.jobs.list(JobStatus.RIPPING))
    return harness.services.jobs.list(JobStatus.RIPPING)[0]


def test_the_rip_card_sums_up_the_changes_and_opens_the_panel(client, harness):
    job = _ripping_bd(harness)
    page = client.get(f"/jobs/{job.id}")
    text = _text(page)
    assert "This Job's settings" in text
    assert "For this Job:" in text and "Default settings" in text  # nothing changed yet
    assert f'aria-controls="jobset-{job.id}"' in page.text
    assert "Can change until Encoding starts." in text and "Can change until Archived." in text
    assert "Quality" in text and "Archives to" in text
    assert "<h3>Rip</h3>" not in page.text  # nothing in ama.toml for a video Rip
    assert "<h3>Identification</h3>" not in page.text
    assert "Slower, smaller (default)" in text

    r = client.post(f"/jobs/{job.id}/settings", data={"key": "encode.quality", "value": "20",
                                                     "summary": "1"}, headers=HX)
    body = _text(r)
    assert "Saved" in body and "Blu-ray default 22" in body and "Reset" in body
    assert 'class="select ov"' in r.text
    assert "Quality 20 (default 22)" in body  # the summary line, swapped out of band
    harness.makemkv.release()


def test_reset_follows_the_default_again(client, harness):
    job = _ripping_bd(harness)
    client.post(f"/jobs/{job.id}/settings", data={"key": "encode.speed", "value": "faster"},
                headers=HX)
    r = client.post(f"/jobs/{job.id}/settings", data={"reset": "encode.speed"}, headers=HX)
    assert "Saved" in _text(r) and "Default Slower" not in _text(r)
    assert harness.services.job_settings.encode_config(job).speed == "slower"
    harness.makemkv.release()


def test_an_edit_that_loses_the_race_with_the_lock_is_refused_with_a_notice(client, harness):
    job = _ripping_bd(harness)
    client.post(f"/jobs/{job.id}/settings", data={"key": "encode.quality", "value": "20"},
                headers=HX)
    harness.services.job_settings.encode_config(job)  # its Encode starts
    r = client.post(f"/jobs/{job.id}/settings",
                    data={"key": "encode.max_resolution", "value": "720p"}, headers=HX)
    body = _text(r)
    assert "Encode wasn't changed" in body
    assert "Your change to Max resolution wasn't saved." in body
    assert "Locked at Encoding start" in body
    assert "Changed for this Job · Blu-ray default 22" in body
    assert harness.services.job_settings.encode_config(job).max_resolution.bd == "keep"
    harness.makemkv.release()


def test_the_logs_run_lists_the_settings_locked_so_far(client, harness):
    job = _ripping_bd(harness)
    harness.services.job_settings.set(job.id, "encode.quality", "20")
    harness.services.job_settings.encode_config(job)
    text = _text(client.get(f"/logs/jobs/{job.id}"))
    assert "Settings used" in text and "Encode locked at" in text
    assert "Quality 20 (changed for this Job)" in text
    assert "Library can still change on the Job page" in text
    harness.makemkv.release()


def test_an_archived_cd_shows_every_group_locked_with_its_stored_values(client, harness):
    from tests.test_cd_archive import COVER, DISC_1, SPECIAL, _insert, _response, _wait_for
    harness.web.covers[SPECIAL] = COVER
    _insert(harness, DISC_1, 24, _response(only=SPECIAL))
    job = _wait_for(harness, JobStatus.ARCHIVED)
    text = _text(client.get(f"/jobs/{job.id}"))
    assert "Locked at Ripping start" in text and "+667 samples" in text
    assert "Locked when Archived" in text and "Archives to Music" in text
    assert "Can change until" not in text
