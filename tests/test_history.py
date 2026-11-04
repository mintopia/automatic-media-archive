"""History: every filed Disc, and what each one is, from what was kept at filing time.

The real app with fakes; the MusicBrainz answer is the real FFVII Rebirth OST
disc 1 capture, cut down to one release so it files on its own. The capture has
no release group or labels (it was made without those `inc`s), so they are added
here the way MusicBrainz sends them.
"""

from __future__ import annotations

import json
from html import unescape

from ama.discs import DiscStatus
from ama.drive import DiscType
from tests.conftest import eventually
from tests.fakes import DATA

DISC_1 = "kIBdaUqY_5kMBgOXehaFmL5TSbA-"
SPECIAL = "139f3172-07da-488b-a4f2-3c6162a2f7cd"
GROUP = "6d4e2c56-3a5b-4a53-9a8e-7a7f6c0b2b11"
ALBUM = "FINAL FANTASY VII REBIRTH Original Soundtrack ～Special edit version～"
COVER = b"\xff\xd8\xff\xe0 fake jpeg"


def _response() -> dict:
    resp = json.loads((DATA / "musicbrainz" / "discid-ffvii-rebirth-disc1.json")
                      .read_text(encoding="utf-8"))
    resp["releases"] = [r for r in resp["releases"] if r["id"] == SPECIAL]
    resp["releases"][0]["release-group"] = {"id": GROUP}
    resp["releases"][0]["label-info"] = [{"catalog-number": "SQEX-11101~8",
                                          "label": {"name": "SQUARE ENIX MUSIC"}}]
    return resp


def _file_ffvii(harness):
    harness.web.musicbrainz[DISC_1] = _response()
    harness.web.covers[SPECIAL] = COVER
    harness.cyanrip.disc_id = DISC_1
    harness.cyanrip.tracks = [(n, 120.0 + n) for n in range(1, 25)]
    harness.cyanrip.ar_confidence = {n: 65 for n in range(1, 25)}
    harness.drive.insert(DiscType.CD)
    eventually(lambda: harness.services.discs.list(DiscStatus.FILED))
    return harness.services.discs.list(DiscStatus.FILED)[0]


def test_a_filed_cds_page_shows_what_it_is_without_scratch_or_the_web(harness, client):
    rec = _file_ffvii(harness)
    eventually(lambda: not rec.scratch_dir.exists())
    harness.web.musicbrainz.clear()   # offline from here: the page uses what filing kept
    harness.web.covers.clear()

    page = unescape(client.get(f"/discs/{rec.id}").text)
    assert ALBUM in page and "Various Artists" in page
    assert "2024" in page and "SQUARE ENIX MUSIC" in page and "SQEX-11101~8" in page
    assert "Disc 1 of 8" in page and "Audio CD" in page
    assert "The Unknown Journey Continues" in page and "2:01" in page   # track 1, 121 s
    assert "Verified (confidence 65)" in page
    assert str(rec.archive_dir) in page   # where it was filed
    for link in (f"https://musicbrainz.org/release/{SPECIAL}",
                 f"https://musicbrainz.org/release-group/{GROUP}",
                 f"https://musicbrainz.org/cdtoc/{DISC_1}",
                 f"https://coverartarchive.org/release/{SPECIAL}"):
        assert f'href="{link}"' in page
    cover = f"/covers/release-{SPECIAL}.jpg"
    assert cover in page
    assert client.get(cover).content == COVER
