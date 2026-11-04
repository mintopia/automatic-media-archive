"""Extras (#8): every ripped Title of a movie Disc that isn't the Main Feature is Encoded
and filed to the film's `Other/` folder with no Review; sorting them later is optional.

The fake BD (tests/data/makemkv-info-bd.txt) rips makemkv Titles 0 and 1: AMA's Title 1
(2:01:33) is the Main Feature, Title 2 (2:31) is an Extra. Every Title is named
"Example Movie" on the Disc, the same as the Disc itself.
"""

from __future__ import annotations

import html

from ama.archive import extended_path
from ama.discs import DiscStatus, TitleRecord, TitleStatus
from ama.drive import DiscType
from ama.extras import default_names
from tests.conftest import eventually

FOLDER = "Example Movie (2016) {tmdb-1234}"


def _film(harness) -> None:
    harness.web.add_film("Example Movie", 1234, "Example Movie", runtime=122)


def _rip_and_file(harness):
    harness.makemkv.release()
    harness.drive.insert(DiscType.BD, "EXAMPLE_MOVIE")
    eventually(lambda: harness.services.discs.list(DiscStatus.FILED), timeout=5)
    return harness.services.discs.list(DiscStatus.FILED)[0]


def _film_folder(harness):
    return extended_path(harness.nas_root / "Movies" / FOLDER)


def test_extras_are_encoded_and_filed_to_other_named_from_the_disc_without_review(
        client, harness):
    harness.makemkv.title_names = {1: "Making Of"}
    _film(harness)
    rec = _rip_and_file(harness)

    extra = _film_folder(harness) / "Other" / "Making Of.mkv"
    assert extra.read_bytes() == b"HEVC Example_Movie_t01.mkv"  # Encoded from the Rip
    eventually(lambda: not rec.scratch_dir.exists())
    eventually(lambda: "Filed 1 Extra to Other" in "\n".join(
        map(str, harness.services.discs.log_lines(rec.id))))


def test_extras_are_named_from_the_disc_unless_the_name_is_just_the_discs():
    def t(number: int, name: str) -> TitleRecord:
        return TitleRecord(number, number, 60, 1, 1, 0, "1", f"t{number}.mkv",
                           TitleStatus.RIPPED, name=name)

    names = default_names([t(2, "Trailer"), t(3, "ARRIVAL"), t(4, ""), t(5, "Trailer"),
                           t(6, "Acoustic Design")], ("Arrival", "ARRIVAL_BD"), "ARRIVAL_BD")
    assert names == {2: "Trailer (Title 2)", 3: "ARRIVAL_BD - Title 3",
                     4: "ARRIVAL_BD - Title 4", 5: "Trailer (Title 5)", 6: "Acoustic Design"}


def test_an_extra_that_fails_to_encode_is_left_out_and_the_film_is_still_filed(
        client, harness):
    harness.ffmpeg.fail_sources = {"Example_Movie_t01.mkv"}
    _film(harness)
    rec = _rip_and_file(harness)

    folder = _film_folder(harness)
    assert (folder / f"{FOLDER} - 1080p.mkv").exists()
    assert not (folder / "Other").exists()
    log = "\n".join(map(str, harness.services.discs.log_lines(rec.id)))
    assert "The Extra “EXAMPLE_MOVIE - Title 2” is left out; the film is filed without it" in log


def test_movie_review_says_the_other_titles_will_be_filed_as_extras(client, harness):
    harness.makemkv.release()
    harness.drive.insert(DiscType.BD, "EXAMPLE_MOVIE")  # no film on TMDB: Review
    eventually(lambda: harness.services.discs.list(DiscStatus.REVIEW), timeout=5)
    page = html.unescape(client.get("/review/1").text)
    assert "<dt>Extras</dt><dd>1 Extra, filed under Other</dd>" in page

    harness.web.add_film("Example Movie", 1234, "Example Movie", runtime=122)
    r = client.post("/review/1/film", data={"film": 1234, "title": 2})  # the short one, oddly
    assert r.status_code == 200
    _rip_and_file_wait(harness)
    assert (_film_folder(harness) / "Other" / "EXAMPLE_MOVIE - Title 1.mkv").read_bytes() == \
        b"HEVC Example_Movie_t00.mkv"


def test_decoy_versions_of_the_film_are_not_extras(client, harness):
    from tests.test_decoys import _heat

    rec = _heat(harness)  # 14 near-identical versions of Heat, then 2 other Titles
    page = html.unescape(client.get(f"/review/{rec.id}").text)
    assert "<dt>Extras</dt><dd>2 Extras, filed under Other</dd>" in page
    client.post(f"/review/{rec.id}/film", data={"film": "949", "title": "6"})
    _rip_and_file_wait(harness)
    other = extended_path(harness.nas_root / "Movies" / "Heat (1995) {tmdb-949}" / "Other")
    assert len(list(other.iterdir())) == 2
    assert len(harness.ffmpeg.encodes()) == 3  # the film and its 2 Extras, no decoys


def _rip_and_file_wait(harness):
    eventually(lambda: harness.services.discs.list(DiscStatus.FILED), timeout=5)
    return harness.services.discs.list(DiscStatus.FILED)[0]


def test_sorting_the_extras_is_offered_in_review_and_moves_them_to_the_plex_folder(
        client, harness):
    harness.makemkv.title_names = {1: "Making Of"}
    _film(harness)
    rec = _rip_and_file(harness)

    queue = html.unescape(client.get("/review").text)
    assert f'href="/discs/{rec.id}/extras"' in queue and "Example Movie (2016)" in queue
    page = html.unescape(client.get(f"/discs/{rec.id}/extras").text)
    assert "Want to sort the Extras for Example Movie (2016)?" in page
    assert "Already filed. Changes are optional." in page
    assert 'value="Making Of"' in page and "Title 2 on the Disc · 3 min" in page
    assert f'src="/discs/{rec.id}/extras/2/50.jpg"' in page  # stills kept after scratch
    assert client.get(f"/discs/{rec.id}/extras/2/50.jpg").content == b"\xff\xd8 fake jpeg"

    scans = len(harness.web.plex_requests)
    r = client.post(f"/discs/{rec.id}/extras",
                    data={"name_2": "The Making of Example Movie", "category_2": "Featurettes"},
                    follow_redirects=False)
    assert r.status_code == 303
    folder = _film_folder(harness)
    moved = folder / "Featurettes" / "The Making of Example Movie.mkv"
    assert moved.read_bytes() == b"HEVC Example_Movie_t01.mkv"
    assert not (folder / "Other" / "Making Of.mkv").exists()
    assert len(harness.web.plex_requests) > scans  # Plex rescans the film's folder
    assert f"/discs/{rec.id}/extras" not in client.get("/review").text  # sorted: off the list
    page = html.unescape(client.get(f"/discs/{rec.id}/extras").text)
    assert 'value="The Making of Example Movie"' in page
    assert '<option selected>Featurettes</option>' in page


def test_leaving_the_extras_as_they_are_takes_them_off_the_review_list(client, harness):
    _film(harness)
    rec = _rip_and_file(harness)
    assert f"/discs/{rec.id}/extras" in client.get("/review").text
    client.post(f"/discs/{rec.id}/extras/leave")
    assert f"/discs/{rec.id}/extras" not in client.get("/review").text
    assert extended_path(_film_folder(harness) / "Other" / "EXAMPLE_MOVIE - Title 2.mkv").exists()


def test_a_filed_film_links_to_its_extras_from_now_and_its_disc_page(client, harness):
    _film(harness)
    rec = _rip_and_file(harness)
    now = html.unescape(client.get("/").text)
    assert f'Movies · 1080p · <a href="/discs/{rec.id}/extras">1 Extra</a>' in now  # History, on Now
    disc = client.get(f"/discs/{rec.id}").text
    assert f'href="/discs/{rec.id}/extras"' in disc
