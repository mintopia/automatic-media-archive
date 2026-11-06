"""CD Identification and archiving to the Archive, end to end: the real app with a fake
drive, cyanrip, Library folders and web (MusicBrainz, Cover Art Archive, Plex).

The MusicBrainz answers are the real capture for FFVII Rebirth OST disc 1
(tests/data/README.md), cut down to one release where a test needs a single match.
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs

from ama import musicbrainz
from ama.archive import extended_path
from ama.flactags import read_tags
from ama.cdarchive import track_tags
from ama.config import LibraryKind
from ama.jobs import JobStatus, ReviewReason
from ama.drive import DiscType
from tests.conftest import eventually
from tests.fakes import DATA

DISC_1 = "kIBdaUqY_5kMBgOXehaFmL5TSbA-"
DISC_2 = "O75dAncJZ7onpacHCAgF4NqupdA-"
SPECIAL = "139f3172-07da-488b-a4f2-3c6162a2f7cd"   # 8 CDs, barcode = the Disc's MCN
ALBUM = "FINAL FANTASY VII REBIRTH Original Soundtrack ～Special edit version～"
COVER = b"\xff\xd8\xff\xe0 fake jpeg"


def _response(only: str | None = None) -> dict:
    resp = json.loads((DATA / "musicbrainz" / "discid-ffvii-rebirth-disc1.json")
                      .read_text(encoding="utf-8"))
    if only:
        resp["releases"] = [r for r in resp["releases"] if r["id"] == only]
    return resp


def _insert(harness, mb_disc_id: str, tracks: int, response) -> None:
    harness.web.musicbrainz[mb_disc_id] = response
    harness.cyanrip.mb_disc_id = mb_disc_id
    harness.cyanrip.tracks = [(n, 120.0) for n in range(1, tracks + 1)]
    harness.cyanrip.ar_confidence = {n: 65 for n in range(1, tracks + 1)}
    harness.drive.insert(DiscType.CD)


def _wait_for(harness, status: JobStatus, count: int = 1):
    eventually(lambda: len(harness.services.jobs.list(status)) == count)
    return harness.services.jobs.list(status)[0]


def _album(harness):
    # Extended-length: with pytest's long tmp path the files are past MAX_PATH.
    return extended_path(harness.libraries_root / "Music" / "Various Artists" / ALBUM)


def test_a_single_release_match_is_tagged_and_archived_with_no_human_interaction(harness, client):
    harness.web.covers[SPECIAL] = COVER
    _insert(harness, DISC_1, 24, _response(only=SPECIAL))

    rec = _wait_for(harness, JobStatus.ARCHIVED)
    eventually(lambda: not rec.scratch_dir.exists())  # deleted right after archiving is verified
    album = _album(harness)
    names = sorted(p.name for p in album.iterdir())
    flacs = [n for n in names if n.endswith(".flac")]
    assert len(flacs) == 24
    assert flacs[0] == "101 - The Unknown Journey Continues.flac"   # disc 1, track 01
    assert f"{ALBUM} (Disc 1).cue" in names and f"{ALBUM} (Disc 1).log" in names
    assert (album / "cover.jpg").read_bytes() == COVER

    tags = read_tags(album / flacs[0])
    assert tags["TITLE"] == ["The Unknown Journey Continues"]
    assert tags["ARTIST"] == ["島翔太朗 & 西木康智"]
    assert tags["ALBUM"] == [ALBUM]
    assert tags["ALBUMARTIST"] == ["Various Artists"]
    assert tags["COMPILATION"] == ["1"]
    assert (tags["TRACKNUMBER"], tags["TRACKTOTAL"]) == (["1"], ["24"])
    assert (tags["DISCNUMBER"], tags["DISCTOTAL"]) == (["1"], ["8"])
    assert tags["DATE"] == ["2024-04-10"]
    assert tags["BARCODE"] == ["4988601470865"]
    assert tags["MUSICBRAINZ_ALBUMID"] == [SPECIAL]
    assert tags["MUSICBRAINZ_ALBUMARTISTID"] == ["89ad4ac3-39f7-470e-963a-56509c546377"]
    assert tags["MUSICBRAINZ_ARTISTID"] == ["e9235369-ddb5-4418-bd98-48af40d6b782",
                                            "181c4177-f33a-441d-b15d-910acaf18b07"]
    assert tags["MUSICBRAINZ_TRACKID"] == ["000e6813-b15d-405d-83ea-7b56b431dca0"]
    assert tags["MUSICBRAINZ_RELEASETRACKID"] == ["bb88f3d1-6d30-4200-bb45-7a15792e54b9"]
    assert tags["MUSICBRAINZ_DISCID"] == [DISC_1]

    cue = (album / f"{ALBUM} (Disc 1).cue").read_text(encoding="utf-8")
    assert 'FILE "101 - The Unknown Journey Continues.flac" WAVE' in cue
    assert 'FILE "01.flac"' not in cue

    assert rec.title == f"{ALBUM} — Various Artists"
    page = client.get("/").text
    assert "History <span class=\"c\">1</span>" in page
    assert f"{ALBUM} — Various Artists" in page
    assert "waiting to be identified" not in page


def test_musicbrainz_is_asked_politely_for_the_disc(harness, client):
    _insert(harness, DISC_1, 24, _response(only=SPECIAL))
    _wait_for(harness, JobStatus.ARCHIVED)
    mb = next(r for r in harness.web.requests if r.url.host == "musicbrainz.org")
    assert mb.url.path == f"/ws/2/discid/{DISC_1}"
    assert "recordings" in mb.url.params["inc"] and mb.url.params["fmt"] == "json"
    assert mb.url.params["cdstubs"] == "no"
    assert mb.headers["user-agent"].startswith("AMA/")
    assert "(" in mb.headers["user-agent"]  # MusicBrainz requires contact info


def test_plex_partially_scans_the_archived_folder(harness, client):
    _insert(harness, DISC_1, 24, _response(only=SPECIAL))
    _wait_for(harness, JobStatus.ARCHIVED)
    eventually(lambda: any(r.url.path.endswith("/refresh") for r in harness.web.plex_requests))
    scan = next(r for r in harness.web.plex_requests if r.url.path.endswith("/refresh"))
    assert scan.url.path == "/library/sections/3/refresh"   # the Music library
    assert parse_qs(scan.url.query.decode())["path"] == [
        f"/volume1/media/Music/Various Artists/{ALBUM}"]
    assert scan.headers["x-plex-token"] == "plex-token"
    assert "plex-token" not in str(scan.url)


def test_discs_of_a_multi_disc_release_file_into_one_album_folder(harness, client):
    _insert(harness, DISC_1, 24, _response(only=SPECIAL))
    _wait_for(harness, JobStatus.ARCHIVED)
    _insert(harness, DISC_2, 23, _response(only=SPECIAL))
    _wait_for(harness, JobStatus.ARCHIVED, count=2)

    names = [p.name for p in _album(harness).iterdir()]
    disc1 = [n for n in names if n.endswith(".flac") and n.startswith("1")]
    disc2 = [n for n in names if n.endswith(".flac") and n.startswith("2")]
    assert (len(disc1), len(disc2)) == (24, 23)
    assert f"{ALBUM} (Disc 2).cue" in names
    tags = read_tags(_album(harness) / sorted(disc2)[0])
    assert (tags["DISCNUMBER"], tags["DISCTOTAL"], tags["TRACKNUMBER"]) == (["2"], ["8"], ["1"])
    assert tags["MUSICBRAINZ_DISCID"] == [DISC_2]


def test_several_matching_releases_are_left_for_review(harness, client):
    _insert(harness, DISC_1, 24, _response())  # 3 releases match

    rec = _wait_for(harness, JobStatus.REVIEW)
    assert rec.review_reason == ReviewReason.MULTIPLE_RELEASES
    assert not (harness.libraries_root / "Music").exists()
    assert sorted(p.name for p in rec.scratch_dir.glob("*.flac"))[0] == "01.flac"
    saved = json.loads((rec.scratch_dir / "musicbrainz.json").read_text(encoding="utf-8"))
    assert len(saved["releases"]) == 3  # what Review will choose from


def test_a_disc_musicbrainz_doesnt_know_is_left_for_review(harness, client):
    _insert(harness, DISC_1, 24, 404)
    rec = _wait_for(harness, JobStatus.REVIEW)
    assert rec.review_reason == ReviewReason.NO_RELEASE
    assert rec.scratch_dir.exists()


def test_a_rip_accuraterip_didnt_verify_is_left_for_review(harness, client):
    harness.web.musicbrainz[DISC_1] = _response(only=SPECIAL)
    harness.cyanrip.mb_disc_id = DISC_1
    harness.cyanrip.tracks = [(n, 120.0) for n in range(1, 25)]
    harness.cyanrip.ar_confidence = {n: 65 for n in range(1, 24)}  # track 24 mismatched
    harness.drive.insert(DiscType.CD)
    rec = _wait_for(harness, JobStatus.REVIEW)
    assert rec.review_reason == ReviewReason.NOT_ACCURATE
    assert not (harness.libraries_root / "Music").exists()


def test_a_cd_not_in_accuraterip_is_left_for_review(harness, client):
    harness.cyanrip.in_accuraterip = False
    _insert(harness, DISC_1, 24, _response(only=SPECIAL))
    rec = _wait_for(harness, JobStatus.REVIEW)
    assert rec.review_reason == ReviewReason.NOT_IN_ACCURATERIP


def test_identification_waits_for_musicbrainz_to_be_reachable(harness, client):
    _insert(harness, DISC_1, 24, None)  # offline
    rec = _wait_for(harness, JobStatus.RIPPED)
    eventually(lambda: any("MusicBrainz" in ln.text for ln in
                           harness.services.jobs.log_lines(rec.id)))
    harness.web.musicbrainz[DISC_1] = _response(only=SPECIAL)
    _wait_for(harness, JobStatus.ARCHIVED)


def test_archiving_waits_for_an_unreachable_library_folder(harness, client):
    folder = harness.drop_library(LibraryKind.MUSIC)
    _insert(harness, DISC_1, 24, _response(only=SPECIAL))
    rec = _wait_for(harness, JobStatus.RIPPED)
    eventually(lambda: any(f"Can't reach the Library folder {folder}" in ln.text
                           for ln in harness.services.jobs.log_lines(rec.id)))
    assert len(list(rec.scratch_dir.glob("*.flac"))) == 24
    harness.restore_library(LibraryKind.MUSIC)
    _wait_for(harness, JobStatus.ARCHIVED)
    assert _album(harness).exists()


def test_labels_listed_once_per_disc_are_tagged_once():
    resp = _response(only=SPECIAL)
    resp["releases"][0]["label-info"] = [
        {"catalog-number": f"SQEX-1110{n}", "label": {"name": "SQUARE ENIX MUSIC"}}
        for n in (2, 3)]
    tags = track_tags(musicbrainz.matches(resp, DISC_1)[0], 1, DISC_1)
    assert tags["LABEL"] == ["SQUARE ENIX MUSIC"]
    assert tags["CATALOGNUMBER"] == ["SQEX-11102", "SQEX-11103"]


# --- the Library's Naming Patterns (#69) -----------------------------------------------------

SINGLE = "{artist} - {album}/{track:02} {track_title}"
MULTI = "{artist} - {album} ({year})/Disc {disc}/{track:02} {track_title}"


def _queen(disc_total: int, disc: int = 1) -> musicbrainz.Match:
    release = musicbrainz.Release("r", "Greatest Hits", "Queen", ("q",), disc_total, "1981")
    return musicbrainz.Match(release, disc, "", (
        musicbrainz.TrackInfo(1, "Bohemian Rhapsody", "Queen", (), "", ""),))


def test_the_releases_disc_count_picks_the_single_or_multi_disc_pattern():
    from pathlib import Path

    from ama.cdarchive import album_folder, track_file
    from ama.config import Library
    music = Library(name="Music", kind=LibraryKind.MUSIC, path=r"C:\Music", pattern=SINGLE,
                    multi_disc_pattern=MULTI)
    assert album_folder(_queen(1), music) == Path("Music/Queen - Greatest Hits")
    assert track_file(_queen(1), 1, "Bohemian Rhapsody", music) == "01 Bohemian Rhapsody.flac"
    assert album_folder(_queen(2, 2), music) == Path("Music/Queen - Greatest Hits (1981)/Disc 2")
    assert track_file(_queen(2, 2), 1, "Bohemian Rhapsody", music) == "01 Bohemian Rhapsody.flac"


def _patterned(tmp_path):
    from tests.conftest import make_harness, write_config
    harness = make_harness(tmp_path, config_file=write_config(tmp_path))
    harness.services.settings.save_library(LibraryKind.MUSIC, "Music", {
        "pattern": SINGLE, "multi_disc_pattern": MULTI})
    return harness


def test_a_multi_disc_release_is_archived_by_the_multi_disc_pattern_with_its_cue_log_and_cover(
        tmp_path):
    from fastapi.testclient import TestClient

    from ama.app import create_app
    harness = _patterned(tmp_path)
    harness.web.covers[SPECIAL] = COVER
    with TestClient(create_app(harness.services)):
        _insert(harness, DISC_1, 24, _response(only=SPECIAL))
        rec = _wait_for(harness, JobStatus.ARCHIVED)
    folder = extended_path(harness.libraries_root / "Music" / f"Various Artists - {ALBUM} (2024)"
                           / "Disc 1")
    names = sorted(p.name for p in folder.iterdir())
    assert names[0] == "01 The Unknown Journey Continues.flac"
    assert len([n for n in names if n.endswith(".flac")]) == 24
    assert {f"{ALBUM} (Disc 1).cue", f"{ALBUM} (Disc 1).log", "cover.jpg"} <= set(names)
    assert rec.archive_dir == harness.libraries_root / "Music" / (
        f"Various Artists - {ALBUM} (2024)") / "Disc 1"


def test_changing_the_pattern_never_renames_an_archived_album(tmp_path):
    from fastapi.testclient import TestClient

    from ama.app import create_app
    harness = _patterned(tmp_path)
    with TestClient(create_app(harness.services)):
        _insert(harness, DISC_1, 24, _response(only=SPECIAL))
        first = _wait_for(harness, JobStatus.ARCHIVED)
        harness.services.settings.save_library(LibraryKind.MUSIC, "Music", {
            "multi_disc_pattern": "{artist}/{album}/{disc}-{track:02} {track_title}"})
        _insert(harness, DISC_2, 23, _response(only=SPECIAL))
        _wait_for(harness, JobStatus.ARCHIVED, count=2)
    old = extended_path(first.archive_dir)
    assert len([p for p in old.iterdir() if p.suffix == ".flac"]) == 24
    assert harness.services.jobs.get(first.id).archive_dir == first.archive_dir
    new = extended_path(harness.libraries_root / "Music" / "Various Artists" / ALBUM)
    flacs = [p.name for p in new.iterdir() if p.suffix == ".flac"]
    assert len(flacs) == 23 and all(n.startswith("2-") for n in flacs)
