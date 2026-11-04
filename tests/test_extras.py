"""Extras (#8): every ripped Title of a movie Disc that isn't the Main Feature is Encoded
and filed to the film's `Other/` folder with no Review; sorting them later is optional.

The fake BD (tests/data/makemkv-info-bd.txt) rips makemkv Titles 0 and 1: AMA's Title 1
(2:01:33) is the Main Feature, Title 2 (2:31) is an Extra. Every Title is named
"Example Movie" on the Disc, the same as the Disc itself.
"""

from __future__ import annotations

import html

from ama.archive import extended_path
from ama.discs import DiscStatus
from ama.drive import DiscType
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
    assert not rec.scratch_dir.exists()
    log = "\n".join(map(str, harness.services.discs.log_lines(rec.id)))
    assert "Filed 1 Extra to Other" in log


def test_an_extra_that_fails_to_encode_is_left_out_and_the_film_is_still_filed(
        client, harness):
    harness.ffmpeg.fail_sources = {"Example_Movie_t01.mkv"}
    _film(harness)
    rec = _rip_and_file(harness)

    folder = _film_folder(harness)
    assert (folder / f"{FOLDER} - 1080p.mkv").exists()
    assert not (folder / "Other").exists()
    log = "\n".join(map(str, harness.services.discs.log_lines(rec.id)))
    assert "The Extra “Title 2” is left out; the film is filed without it" in log


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
    assert extended_path(_film_folder(harness) / "Other" / "Title 2.mkv").exists()
