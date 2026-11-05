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
    assert "matches 65 other rips" in page
    assert str(rec.archive_dir) in page   # where it was filed
    for link in (f"https://musicbrainz.org/release/{SPECIAL}",
                 f"https://musicbrainz.org/release-group/{GROUP}",
                 f"https://musicbrainz.org/cdtoc/{DISC_1}",
                 f"https://coverartarchive.org/release/{SPECIAL}"):
        assert f'href="{link}"' in page
    cover = f"/covers/release-{SPECIAL}.jpg"
    assert cover in page
    assert client.get(cover).content == COVER


def test_history_lists_filed_discs_with_a_cover_thumbnail_in_the_nav_and_on_now(harness, client):
    rec = _file_ffvii(harness)
    cover = f"/covers/release-{SPECIAL}.jpg"

    page = unescape(client.get("/history").text)
    assert "<title>History · Automatic Media Archive</title>" in page
    assert '<a href="/history" aria-current="page">History</a>' in page   # in the nav
    row = page[page.index(f'href="/discs/{rec.id}"') - 400:]
    assert cover in row[:800] and ALBUM in row[:800]

    assert "24 tracks · verified" in row
    names = row[row.index("<details"):row.index("</details>")]
    assert "<summary" in names and "The Unknown Journey Continues" in names  # track 1
    summary = names[:names.index("</summary>")]
    assert "<a " not in summary  # nothing to click inside the toggle
    assert f'href="https://musicbrainz.org/release/{SPECIAL}"' in row[:row.index("</details>")]
    assert ">MusicBrainz</a>" in row

    now = unescape(client.get("/").text)
    assert '<a href="/history">History</a>' in now
    assert "Filed today" not in now
    assert 'History <span class="c">1</span>' in now and cover in now


def test_the_section_is_called_history_on_every_disc_page_never_ripped_or_filed(harness, client):
    harness.cyanrip.disc_id = DISC_1   # MusicBrainz offline: it stays ripped, waiting
    harness.cyanrip.tracks = [(n, 120.0) for n in range(1, 25)]
    harness.drive.insert(DiscType.CD)
    eventually(lambda: harness.services.discs.list(DiscStatus.RIPPED))
    rec = harness.services.discs.list(DiscStatus.RIPPED)[0]
    page = unescape(client.get(f"/discs/{rec.id}").text)
    crumb = page[page.index('class="crumb"'):]
    crumb = crumb[:crumb.index("</div>")]
    assert '<a href="/history">History</a>' in crumb and "Ripped" not in crumb
    assert "· History · Automatic Media Archive</title>" in page


def test_history_is_empty_until_something_is_filed(client):
    page = unescape(client.get("/history").text)
    assert "Nothing filed yet" in page


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
    history = unescape(client.get("/history").text)
    history = history[history.index("<main"):]
    names = history[history.index("<details"):history.index("</details>")]
    assert "S01E02 · Work Experience" in names
    assert 'href="https://www.themoviedb.org/tv/2996" rel="noreferrer" target="_blank">TMDB'         in history
    assert 'href="https://www.themoviedb.org/tv/2996"' in page
    assert client.get("/covers/tmdb-tv-2996.jpg").content == POSTER


def _forget_media(harness, rec) -> None:
    """As if `rec` was filed before History kept what each Disc is (migration 0012)."""
    harness.services.db.execute("DELETE FROM media_info WHERE disc_id = ?", (rec.id,))
    for f in harness.services.covers.folder.glob("*"):
        f.unlink()


def test_discs_filed_before_history_kept_their_details_get_them_at_startup(harness, client):
    import asyncio
    cd = _file_ffvii(harness)
    eventually(lambda: not cd.scratch_dir.exists())
    harness.drive.eject()
    harness.web.add_film("Example Movie", 1234, "Example Movie", runtime=122,
                         poster_path="/ex1234.jpg")
    harness.web.tmdb_images["/ex1234.jpg"] = POSTER
    harness.makemkv.release()
    harness.drive.insert(DiscType.BD, "EXAMPLE_MOVIE")
    eventually(lambda: len(harness.services.discs.list(DiscStatus.FILED)) == 2)
    film = next(r for r in harness.services.discs.list(DiscStatus.FILED) if r.id != cd.id)
    for rec in (cd, film):
        _forget_media(harness, rec)
    assert "The Unknown Journey Continues" not in unescape(client.get("/history").text)

    asyncio.run(harness.services.backfill.run())
    page = unescape(client.get(f"/discs/{cd.id}").text)
    assert "The Unknown Journey Continues" in page and f"/covers/release-{SPECIAL}.jpg" in page
    assert client.get(f"/covers/release-{SPECIAL}.jpg").content == COVER
    assert "/covers/tmdb-movie-1234.jpg" in unescape(client.get(f"/discs/{film.id}").text)

    lookups = len(harness.web.requests)
    asyncio.run(harness.services.backfill.run())  # nothing left to fill in: no requests
    assert len(harness.web.requests) == lookups
