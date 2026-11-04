"""Repeat-Disc warning (#16): an archived Disc put back in the drive is not ripped
until the user chooses to skip it (eject) or archive it again.

Discs are remembered by fingerprint: the MusicBrainz Disc ID for CDs, a hash of the
Disc's file structure for video, so a BD and a UHD of the same film are different Discs.
"""

from __future__ import annotations

import html
import json

from ama.discs import DiscStatus
from ama.drive import DiscType
from ama.repeat import video_fingerprint
from tests.conftest import eventually
from tests.fakes import DATA

DISC_1 = "kIBdaUqY_5kMBgOXehaFmL5TSbA-"
SPECIAL = "139f3172-07da-488b-a4f2-3c6162a2f7cd"
ALBUM = "FINAL FANTASY VII REBIRTH Original Soundtrack ～Special edit version～"
WARNING = "You've archived this Disc before"


def _page(client, url: str = "/") -> str:
    return html.unescape(client.get(url).text)


def _file_cd(harness) -> None:
    resp = json.loads((DATA / "musicbrainz" / "discid-ffvii-rebirth-disc1.json")
                      .read_text(encoding="utf-8"))
    resp["releases"] = [r for r in resp["releases"] if r["id"] == SPECIAL]
    harness.web.musicbrainz[DISC_1] = resp
    harness.cyanrip.disc_id = DISC_1
    harness.cyanrip.tracks = [(n, 120.0) for n in range(1, 25)]
    harness.cyanrip.ar_confidence = {n: 65 for n in range(1, 25)}
    harness.drive.insert(DiscType.CD)
    eventually(lambda: harness.services.discs.list(DiscStatus.FILED))


def _rips(harness) -> int:
    return sum(1 for c in harness.cyanrip.calls if "-I" not in c)


def _bd(tmp_path, name: str, files: dict[str, int]):
    """A Blu-ray's filesystem: BDMV files of the given sizes."""
    root = tmp_path / name
    for rel, size in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\0" * size)
    return root


BD_FILES = {"BDMV/index.bdmv": 120, "BDMV/PLAYLIST/00800.mpls": 300,
            "BDMV/CLIPINF/00001.clpi": 400, "BDMV/STREAM/00001.m2ts": 5000}
UHD_FILES = {"BDMV/index.bdmv": 124, "BDMV/PLAYLIST/00800.mpls": 310,
             "BDMV/CLIPINF/00001.clpi": 420, "BDMV/STREAM/00001.m2ts": 9000}


def _file_movie(harness, root, disc_type=DiscType.BD) -> None:
    harness.web.add_film("Example Movie", 1234, "Example Movie", runtime=122)
    harness.drive.root = root
    harness.makemkv.release()
    harness.drive.insert(disc_type, "EXAMPLE_MOVIE")
    eventually(lambda: harness.services.discs.list(DiscStatus.FILED), timeout=5)
    harness.drive.eject()


# -- CD --------------------------------------------------------------------------

def test_a_known_cd_is_recognised_on_insert_and_not_ripped(harness, client):
    _file_cd(harness)
    harness.drive.eject()
    rips = _rips(harness)

    harness.drive.insert(DiscType.CD)
    eventually(lambda: WARNING in _page(client))
    page = _page(client)
    assert f"{ALBUM} — Various Artists" in page and "Audio CD" in page
    assert "Paused until you choose" in page
    assert f"Music/Various Artists/{ALBUM}" in page
    assert "Waiting for your choice on" in page  # the Ripping bin
    assert _rips(harness) == rips
    assert len(harness.services.discs.list(DiscStatus.FILED)) == 1


def test_skip_ejects_the_known_disc_without_ripping(harness, client):
    _file_cd(harness)
    harness.drive.eject()
    ejected, rips = harness.drive.ejected, _rips(harness)
    harness.drive.insert(DiscType.CD)
    eventually(lambda: WARNING in _page(client))

    r = client.post("/repeat/skip", follow_redirects=False)
    assert r.status_code == 303
    eventually(lambda: harness.drive.ejected == ejected + 1)
    assert WARNING not in _page(client)
    assert _rips(harness) == rips
    assert harness.services.discs.list(DiscStatus.RIPPING) == []
    assert len(harness.services.discs.list(DiscStatus.FILED)) == 1


def test_archive_again_rips_and_files_the_disc_normally(harness, client):
    _file_cd(harness)
    harness.drive.eject()
    harness.drive.insert(DiscType.CD)
    eventually(lambda: WARNING in _page(client))

    client.post("/repeat/again")
    eventually(lambda: len(harness.services.discs.list(DiscStatus.FILED)) == 2)
    assert WARNING not in _page(client)


def test_taking_the_disc_out_while_asked_clears_the_warning(harness, client):
    _file_cd(harness)
    harness.drive.eject()
    rips = _rips(harness)
    harness.drive.insert(DiscType.CD)
    eventually(lambda: WARNING in _page(client))

    harness.drive.eject()  # by hand
    eventually(lambda: WARNING not in _page(client))
    assert _rips(harness) == rips


def test_a_different_cd_is_ripped_without_asking(harness, client):
    _file_cd(harness)
    harness.drive.eject()
    harness.cyanrip.disc_id = "O75dAncJZ7onpacHCAgF4NqupdA-"  # disc 2 of the same album
    rips = _rips(harness)
    harness.drive.insert(DiscType.CD)
    eventually(lambda: _rips(harness) == rips + 1)
    assert WARNING not in _page(client)


def test_a_cd_ripped_but_not_yet_filed_is_a_repeat_waiting_to_be_filed(harness, client):
    harness.cyanrip.disc_id = DISC_1  # MusicBrainz offline: Ripped, never filed
    harness.drive.insert(DiscType.CD)
    eventually(lambda: harness.drive.ejected == 1)
    rips = _rips(harness)
    harness.drive.insert(DiscType.CD)
    eventually(lambda: "You've ripped this Disc already" in _page(client))
    assert "Already ripped, waiting to be filed" in _page(client)
    assert _rips(harness) == rips


def test_a_cd_waiting_in_review_is_a_repeat_waiting_for_review(harness, client):
    harness.web.musicbrainz[DISC_1] = 404  # not on MusicBrainz: Review
    harness.cyanrip.disc_id = DISC_1
    harness.drive.insert(DiscType.CD)
    eventually(lambda: harness.services.discs.list(DiscStatus.REVIEW))
    harness.drive.eject()
    harness.drive.insert(DiscType.CD)
    eventually(lambda: "Already ripped, waiting for Review" in _page(client))


def test_a_known_cd_is_recognised_before_scratch_is_checked_and_again_after_archive_again(
        harness, client):
    _file_cd(harness)
    harness.drive.eject()
    ejected, rips = harness.drive.ejected, _rips(harness)
    harness.disk.used = harness.disk.total - 1000**3 // 2  # scratch full
    harness.drive.insert(DiscType.CD)
    eventually(lambda: WARNING in _page(client))
    assert harness.drive.ejected == ejected and harness.services.scratch.refused is None

    client.post("/repeat/again")
    eventually(lambda: harness.drive.ejected == ejected + 1)
    assert harness.services.scratch.refused is not None  # not ripped: no room
    assert _rips(harness) == rips


# -- video -----------------------------------------------------------------------

def test_a_known_blu_ray_is_recognised_and_skip_ejects_it(harness, client, tmp_path):
    root = _bd(tmp_path, "bd", BD_FILES)
    _file_movie(harness, root)
    ejected, rips = harness.drive.ejected, len(harness.makemkv.ripped_ids)

    harness.drive.insert(DiscType.BD, "EXAMPLE_MOVIE")
    eventually(lambda: WARNING in _page(client))
    page = _page(client)
    assert "Example Movie (2016) · Blu-ray · filed" in page
    assert "Movies/Example Movie (2016) {tmdb-1234}" in page
    assert "The UHD Blu-ray of Example Movie (2016) is a different Disc" in page

    client.post("/repeat/skip")
    eventually(lambda: harness.drive.ejected == ejected + 1)
    assert len(harness.makemkv.ripped_ids) == rips
    assert len(harness.services.discs.list(DiscStatus.FILED)) == 1


def test_the_uhd_of_an_archived_blu_ray_is_not_a_repeat(harness, client, tmp_path):
    _file_movie(harness, _bd(tmp_path, "bd", BD_FILES))
    rips = len(harness.makemkv.ripped_ids)

    harness.drive.root = _bd(tmp_path, "uhd", UHD_FILES)
    harness.drive.insert(DiscType.UHD, "EXAMPLE_MOVIE")
    eventually(lambda: len(harness.makemkv.ripped_ids) > rips)
    assert WARNING not in _page(client)


# -- fingerprints ------------------------------------------------------------------

def test_video_fingerprint_follows_the_disc_structure(tmp_path):
    bd = video_fingerprint(_bd(tmp_path, "a", BD_FILES), DiscType.BD)
    assert bd == video_fingerprint(_bd(tmp_path, "b", BD_FILES), DiscType.BD)  # same pressing
    assert bd != video_fingerprint(_bd(tmp_path, "c", UHD_FILES), DiscType.BD)
    other_cut = {**BD_FILES, "BDMV/STREAM/00002.m2ts": 7000}
    assert bd != video_fingerprint(_bd(tmp_path, "d", other_cut), DiscType.BD)
    assert bd != video_fingerprint(_bd(tmp_path, "e", BD_FILES), DiscType.UHD)
    assert video_fingerprint(tmp_path / "missing", DiscType.BD) is None
    assert video_fingerprint(None, DiscType.BD) is None


def test_cd_fingerprint_is_the_musicbrainz_disc_id_from_the_real_ffvii_toc():
    from ama import cyanrip
    from ama.repeat import cd_fingerprint

    report = cyanrip.parse_report((DATA / "cyanrip" / "info-ffvii-rebirth-disc1.txt")
                                  .read_text(encoding="utf-8"))
    assert cd_fingerprint(report.disc_id) == f"CD:{DISC_1}"
    assert cd_fingerprint(None) is None
