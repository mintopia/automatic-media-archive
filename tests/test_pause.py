"""Paused: AMA ignores newly inserted Discs; a Rip under way finishes and every other
Phase carries on. Toggled from the top-bar menu ("New Discs"), kept across restarts."""

from __future__ import annotations

import html
import time

import pytest
from fastapi.testclient import TestClient

from ama.app import create_app
from ama.discs import DiscStatus
from ama.drive import DiscType
from tests.conftest import eventually, make_harness


def _settle() -> None:
    """Long enough for many drive polls (0.01 s) and ripper checks."""
    time.sleep(0.4)


def _jobs(harness) -> int:
    return len(harness.services.discs.statuses())


def _pause(client) -> None:
    assert client.post("/pause", headers={"referer": "/"}).status_code in (200, 303)


def _resume(client) -> None:
    assert client.post("/resume", headers={"referer": "/"}).status_code in (200, 303)


@pytest.mark.parametrize("disc_type", [DiscType.BD, DiscType.CD])
def test_a_disc_inserted_while_paused_starts_no_job_until_resumed(client, harness, disc_type):
    harness.makemkv.release()
    _pause(client)
    harness.drive.insert(disc_type, "EXAMPLE_MOVIE")
    _settle()
    assert _jobs(harness) == 0 and harness.drive.ejected == 0

    _resume(client)
    eventually(lambda: _jobs(harness) == 1)
    eventually(lambda: harness.drive.ejected == 1)


def test_a_rip_under_way_finishes_when_paused(client, harness):
    harness.drive.insert(DiscType.DVD, "HEAT_DISC1")
    eventually(lambda: "Title 1 of 2" in html.unescape(client.get("/disc").text))
    _pause(client)
    harness.makemkv.release()
    eventually(lambda: harness.drive.ejected == 1)
    assert harness.services.discs.get(1).status != DiscStatus.FAILED
    assert len(harness.makemkv.ripped_ids) == 2  # both Titles, not cut short


def test_filing_carries_on_while_paused(tmp_path):
    from tests.test_cd_archive import DISC_1, SPECIAL, _insert, _response, _wait_for

    harness = make_harness(tmp_path, nas_reachable=False)
    with TestClient(create_app(harness.services)) as client:
        _insert(harness, DISC_1, 24, _response(only=SPECIAL))
        _wait_for(harness, DiscStatus.RIPPED)
        _pause(client)
        harness.share["reachable"] = True
        _wait_for(harness, DiscStatus.FILED)


def test_paused_survives_a_restart(tmp_path):
    first = make_harness(tmp_path)
    with TestClient(create_app(first.services)) as client:
        _pause(client)
    first.services.db.close()

    again = make_harness(tmp_path)
    with TestClient(create_app(again.services)) as client:
        assert 'class="paused"' in client.get("/").text
        again.makemkv.release()
        again.drive.insert(DiscType.BD, "EXAMPLE_MOVIE")
        _settle()
        assert _jobs(again) == 0
        _resume(client)
        eventually(lambda: _jobs(again) == 1)


def test_the_top_bar_shows_paused_and_the_menu_says_which(client):
    page = client.get("/").text
    assert 'class="paused"' not in page
    assert 'formaction="/resume" aria-pressed="true"' in page

    r = client.post("/pause", headers={"referer": "/history"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/history"
    page = client.get("/history").text
    assert 'class="paused"' in page and "New Discs are ignored until you resume" in page
    assert 'formaction="/pause" aria-pressed="true"' in page
    assert 'formaction="/resume" aria-pressed="false"' in page

    _resume(client)
    assert 'class="paused"' not in client.get("/").text


def test_settings_general_says_whether_new_discs_are_taken(tmp_path):
    from tests.conftest import write_config

    h = make_harness(tmp_path, config_file=write_config(tmp_path))
    with TestClient(create_app(h.services)) as client:
        page = html.unescape(client.get("/settings/general").text)
        assert "New Discs" in page and "Right now" in page
        assert "<b>Accepting</b>" in page and "Change in the menu" in page
        _pause(client)
        page = html.unescape(client.get("/settings/general").text)
        assert "<b>Paused</b>" in page and "until you resume" in page
