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


POSTER = b"\xff\xd8\xff\xe0 fake poster"


def test_a_filed_films_page_shows_its_poster_overview_and_tmdb_link(harness, client):
    harness.web.add_film("Example Movie", 1234, "Example Movie", runtime=122,
                         overview="Examples are made.", poster_path="/ex1234.jpg")
    harness.web.tmdb_images["/ex1234.jpg"] = POSTER
    harness.makemkv.release()
    harness.drive.insert(DiscType.BD, "EXAMPLE_MOVIE")
    eventually(lambda: harness.services.discs.list(DiscStatus.FILED))
    rec = harness.services.discs.list(DiscStatus.FILED)[0]
    harness.web.tmdb_offline = True   # the page uses what filing kept

    page = unescape(client.get(f"/discs/{rec.id}").text)
    assert "Example Movie" in page and "2016" in page and "Examples are made." in page
    assert 'href="https://www.themoviedb.org/movie/1234"' in page
    assert str(rec.archive_dir) in page and "Blu-ray" in page
    assert "/covers/tmdb-movie-1234.jpg" in page
    assert client.get("/covers/tmdb-movie-1234.jpg").content == POSTER


def test_a_film_is_filed_even_when_tmdb_cant_give_its_poster(harness, client):
    harness.web.add_film("Example Movie", 1234, "Example Movie", runtime=122,
                         poster_path="/missing.jpg")
    harness.makemkv.release()
    harness.drive.insert(DiscType.BD, "EXAMPLE_MOVIE")
    eventually(lambda: harness.services.discs.list(DiscStatus.FILED))
    rec = harness.services.discs.list(DiscStatus.FILED)[0]
    page = unescape(client.get(f"/discs/{rec.id}").text)
    assert 'href="https://www.themoviedb.org/movie/1234"' in page
    assert "/covers/" not in page


def test_a_filed_tv_discs_page_shows_the_series_poster_overview_and_tmdb_link(harness, client):
    from tests.test_tv_review import OFFICE, _in_review, _tv_disc
    harness.web.add_series("THE OFFICE", OFFICE, "The Office", 2001, {
        1: [(1, "Downsize", 30), (2, "Work Experience", 29), (3, "The Quiz", 29)]},
        overview="A mockumentary about an office.", poster_path="/office.jpg")
    harness.web.tmdb_images["/office.jpg"] = POSTER
    rec = _in_review(harness, _tv_disc(harness))
    client.post(f"/review/{rec.id}/episodes", data={
        "series": str(OFFICE), "season": "1", "t1": "S01E01", "t2": "S01E02", "t3": "S01E03",
        "t4": "discard", "t5": "discard"})
    eventually(lambda: harness.services.discs.get(rec.id).status == DiscStatus.FILED, timeout=10)

    page = unescape(client.get(f"/discs/{rec.id}").text)
    assert "The Office" in page and "A mockumentary about an office." in page
    assert "3 Episodes" in page
    assert 'href="https://www.themoviedb.org/tv/2996"' in page
    assert client.get("/covers/tmdb-tv-2996.jpg").content == POSTER
