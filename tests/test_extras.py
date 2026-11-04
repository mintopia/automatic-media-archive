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
