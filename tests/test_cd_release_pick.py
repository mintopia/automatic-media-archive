"""While a CD rips, the user can pick which of the MusicBrainz releases it is, from the rip
card. The pick is stored on the Job at once: the cards, track titles and cover follow it,
and Review offers it pre-selected.

Fixtures: the real FFVII Rebirth OST disc 1 MusicBrainz answer (3 releases that fit).
"""

from __future__ import annotations

import re
from html import unescape

from ama.jobs import JobStatus
from tests.conftest import eventually
from tests.test_cd_guess import COVER, SPECIAL, STANDARD, _response, _rip_held, eventually_status

PSEUDO = "5afc3090-044d-4f34-a188-a273b8cf6e0e"  # English track titles, no cover
STANDARD_COVER = b"\xff\xd8\xff\xe0 standard jpeg"


def _job_id(harness, client) -> int:
    eventually(lambda: "Likely" in client.get("/").text)
    return harness.services.cd.current.job_id


def test_every_release_that_fits_can_be_picked_from_the_rip_card(harness, client):
    _rip_held(harness, _response())
    job = _job_id(harness, client)

    card = client.get(f"/jobs/{job}").text
    assert f'href="/jobs/{job}/release"' in card
    assert f'href="/jobs/{job}/release"' in client.get("/").text   # the Now drive card too
    picker = client.get(f"/jobs/{job}/release").text
    for release in (SPECIAL, PSEUDO, STANDARD):
        assert f'value="{release}:1"' in picker
    assert re.search(rf'value="{SPECIAL}:1"[^>]*checked', picker)   # the likely one, for now

    r = client.post(f"/jobs/{job}/release", data={"release": f"{PSEUDO}:1"},
                    follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/jobs/{job}"
    page = unescape(client.get(f"/jobs/{job}").text)
    assert "Another Buster Sword" in page   # track 2, as the picked release titles it
    assert "Your pick" in page and "Likely" not in page
    assert re.search(rf'value="{PSEUDO}:1"[^>]*checked', client.get(f"/jobs/{job}/release").text)
    harness.cyanrip.release()


def test_the_cover_follows_the_picked_release(harness, client):
    harness.web.covers[SPECIAL] = COVER
    harness.web.covers[STANDARD] = STANDARD_COVER
    _rip_held(harness, _response())
    job = _job_id(harness, client)
    eventually(lambda: f"release-{SPECIAL}" in client.get("/").text)

    client.post(f"/jobs/{job}/release", data={"release": f"{STANDARD}:1"})
    now = unescape(client.get("/").text)
    cover = f"/covers/release-{STANDARD}.jpg"
    assert cover in now and f"release-{SPECIAL}" not in now
    assert "Special edit version" not in now   # the standard edition's title
    assert "Your pick · Track 3 of 24" in now and "Likely" not in now   # the Ripping bin too
    assert client.get(cover).content == STANDARD_COVER
    harness.cyanrip.release()


def test_the_pick_stays_on_the_job_after_the_rip_and_review_offers_it(harness, client):
    harness.web.covers[STANDARD] = STANDARD_COVER
    _rip_held(harness, _response())
    job = _job_id(harness, client)
    client.post(f"/jobs/{job}/release", data={"release": f"{STANDARD}:1"})
    harness.cyanrip.release()
    eventually_status(harness, JobStatus.REVIEW)

    queue = unescape(client.get("/review").text)
    assert "FINAL FANTASY VII REBIRTH Original Soundtrack — Various Artists" in queue
    review = client.get(f"/review/{job}").text
    assert re.search(rf'value="{STANDARD}:1"[^>]*checked', review)
    assert not re.search(rf'value="{SPECIAL}:1"[^>]*checked', review)
    assert "Which edition of FINAL FANTASY VII REBIRTH Original Soundtrack is this?" in \
        unescape(review)
    assert review.index(f'value="{STANDARD}:1"') < review.index(f'value="{SPECIAL}:1"')
    page = unescape(client.get(f"/jobs/{job}").text)
    assert "Your pick" in page and f"/covers/release-{STANDARD}.jpg" in page
    assert "Special edit version" not in page
    assert "The Unknown Journey Continues" in page   # the picked release's track titles


def test_only_an_offered_release_of_the_cd_being_ripped_can_be_picked(harness, client):
    _rip_held(harness, _response())
    job = _job_id(harness, client)
    assert client.post(f"/jobs/{job}/release", data={"release": "nope:1"}).status_code == 400
    assert client.post(f"/jobs/{job}/release",
                       data={"release": f"{STANDARD}:2"}).status_code == 400   # not this disc
    harness.cyanrip.release()
    eventually_status(harness, JobStatus.REVIEW)
    r = client.post(f"/jobs/{job}/release", data={"release": f"{STANDARD}:1"},
                    follow_redirects=False)
    assert r.status_code == 409   # the Rip is over: Review decides now
