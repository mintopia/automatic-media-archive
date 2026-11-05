"""While a CD rips, AMA shows a likely guess at what it is (MusicBrainz + Cover Art
Archive, looked up from the TOC). The guess is only for show: Identification and
Review still decide, and the guess never files anything.

Fixtures: the real FFVII Rebirth OST disc 1 MusicBrainz answer (3 releases).
"""

from __future__ import annotations

import json
from html import unescape

from ama import musicbrainz
from ama.cdguess import likely
from ama.cdrip import Track
from ama.discs import DiscStatus
from ama.drive import DiscType
from tests.conftest import eventually
from tests.fakes import DATA

DISC_1 = "kIBdaUqY_5kMBgOXehaFmL5TSbA-"
SPECIAL = "139f3172-07da-488b-a4f2-3c6162a2f7cd"    # barcode 4988601470865 = the Disc's MCN
STANDARD = "b543589a-95c2-4c29-ba33-f9137ff8eb4c"   # 7 CDs, barcode 4988601470872
ALBUM = "FINAL FANTASY VII REBIRTH Original Soundtrack ～Special edit version～"
COVER = b"\xff\xd8\xff\xe0 fake jpeg"


def _response() -> dict:
    return json.loads((DATA / "musicbrainz" / "discid-ffvii-rebirth-disc1.json")
                      .read_text(encoding="utf-8"))


def _tracks(n: int) -> list[Track]:
    return [Track(i, 120.0) for i in range(1, n + 1)]


def test_the_release_whose_barcode_is_the_discs_mcn_is_the_likely_one():
    found = musicbrainz.matches(_response(), DISC_1)
    assert likely(_tracks(24), found, "4988601470872") == (
        next(m for m in found if m.release.id == STANDARD), 3)
    match, count = likely(_tracks(24), found, "4988601470865")
    assert (match.release.id, count) == (SPECIAL, 3)


def test_without_an_mcn_an_official_release_is_preferred_over_a_pseudo_release():
    found = musicbrainz.matches(_response(), DISC_1)
    pseudo_first = sorted(found, key=lambda m: m.release.status != "Pseudo-Release")
    match, count = likely(_tracks(24), pseudo_first, None)
    assert match.release.status == "Official" and count == 3


def test_releases_whose_disc_has_another_track_count_are_not_counted():
    found = musicbrainz.matches(_response(), DISC_1)
    assert likely(_tracks(23), found, "4988601470865") == (None, 0)
    assert likely(_tracks(24), [], None) == (None, 0)


def _rip_held(harness, response) -> None:
    """Insert the FFVII disc and hold its Rip half-way through track 3."""
    if response is not None:
        harness.web.musicbrainz[DISC_1] = response
    harness.cyanrip.disc_id = DISC_1
    harness.cyanrip.mcn = "4988601470865"
    harness.cyanrip.tracks = [(n, 120.0) for n in range(1, 25)]
    harness.cyanrip.ar_confidence = {n: 65 for n in range(1, 25)}
    harness.cyanrip.hold_at = 3
    harness.drive.insert(DiscType.CD)
    harness.cyanrip.wait_until_held()


def test_while_ripping_the_likely_album_cover_and_track_titles_are_shown(harness, client):
    harness.web.covers[SPECIAL] = COVER
    _rip_held(harness, _response())

    eventually(lambda: "Likely" in client.get("/").text)
    now = unescape(client.get("/").text)
    assert ALBUM in now and "Various Artists" in now
    assert "1 of 3 versions of this album" in now
    cover = f"/covers/release-{SPECIAL}.jpg"
    assert cover in now
    assert client.get(cover).content == COVER

    disc = harness.services.cd.current.disc_id
    page = unescape(client.get(f"/discs/{disc}").text)
    assert "The Unknown Journey Continues" in page   # track 1's title on MusicBrainz
    assert "1 of 3 versions of this album" in page and cover in page

    harness.cyanrip.release()
    rec = eventually_status(harness, DiscStatus.REVIEW)   # the guess never files anything
    assert not (harness.nas_root / "Music").exists()
    assert rec.title == ""


def test_while_musicbrainz_is_unreachable_the_disc_id_and_track_count_are_shown_and_it_retries(
        harness, client):
    harness.services.cd.guess_retry_seconds = 0.05
    _rip_held(harness, 503)
    eventually(lambda: any(r.url.host == "musicbrainz.org" for r in harness.web.requests))
    now = unescape(client.get("/").text)
    assert "Likely" not in now
    assert DISC_1 in now and "24 tracks" in now
    assert "503" not in now and "error" not in now.lower()

    harness.web.musicbrainz[DISC_1] = _response()   # MusicBrainz is back
    eventually(lambda: "Likely" in client.get("/").text)
    harness.cyanrip.release()


def eventually_status(harness, status: DiscStatus):
    eventually(lambda: harness.services.discs.list(status))
    return harness.services.discs.list(status)[0]
