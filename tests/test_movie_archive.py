"""Movie Identification, Encode and filing, end to end: the real app with a fake drive,
makemkvcon, ffmpeg/ffprobe, NAS folder and web (TMDB, Plex).

The fake BD (tests/data/makemkv-info-bd.txt) is "Example Movie", label EXAMPLE_MOVIE;
its Main Feature (Title 1) runs 2:01:33, i.e. 121.5 minutes.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from urllib.parse import parse_qs

import pytest

from ama.archive import extended_path
from ama.config import Config
from ama.discs import DiscStatus, ReviewReason
from ama.drive import DiscType
from ama.moviearchive import EncodeStatus
from tests.conftest import eventually, make_harness
from tests.fakes import HDR10_FRAME, probe_stream

FOLDER = "Example Movie (2016) {tmdb-1234}"


def _rip(harness, label="EXAMPLE_MOVIE", disc_type=DiscType.BD) -> None:
    harness.makemkv.release()
    harness.drive.insert(disc_type, label)
    eventually(lambda: harness.drive.ejected >= 1)


def _wait_for(harness, status: DiscStatus):
    eventually(lambda: harness.services.discs.list(status), timeout=5)
    return harness.services.discs.list(status)[0]


def _filed(harness, version="1080p"):
    return extended_path(harness.nas_root / "Movies" / FOLDER / f"{FOLDER} - {version}.mkv")


def _uhd_source(harness) -> None:
    """The Main Feature of a UHD: 4K HEVC with HDR10 metadata."""
    harness.ffmpeg.streams[0] = probe_stream(0, "video", "hevc", height=2160)
    harness.ffmpeg.frame = HDR10_FRAME


def test_a_confident_match_is_encoded_and_filed_with_no_human_interaction(client, harness):
    harness.web.add_film("Example Movie", 1234, "Example Movie", runtime=122)
    _rip(harness)

    rec = _wait_for(harness, DiscStatus.FILED)
    assert rec.title == "Example Movie (2016)"
    assert _filed(harness).read_bytes() == b"HEVC Example_Movie_t00.mkv"  # the Main Feature
    eventually(lambda: not rec.scratch_dir.exists())  # the lossless Rip is gone (ADR-0002)
    def scans():  # Plex is told after the Disc is marked filed
        return [r for r in harness.web.plex_requests if "/refresh" in r.url.path]
    eventually(lambda: bool(scans()))
    scan = scans()
    assert scan[0].url.path == "/library/sections/1/refresh"
    assert parse_qs(scan[0].url.query.decode())["path"] == [f"/volume1/media/Movies/{FOLDER}"]
    encode = harness.ffmpeg.encodes()[0]
    assert encode[encode.index("-cq") + 1] == "22"  # BD's CQ from config
    log = "\n".join(map(str, harness.services.discs.log_lines(rec.id)))
    assert "Identified as Example Movie (2016)" in log and "Encode finished" in log
    page = html.unescape(client.get("/").text)
    assert "Example Movie (2016)" in page and "Movies · 1080p" in page  # History, on Now


def test_a_film_is_filed_to_the_films_default_library_and_plex_scans_that_library(
        client, harness):
    nas = harness.nas_root
    cfg = harness.services.config
    libraries = [
        {"name": "Movies", "kind": "films", "path": str(nas / "Movies"), "plex": "Movies"},
        {"name": "Films", "kind": "films", "path": str(nas / "Films HD"), "plex": "Films",
         "default": True},
        {"name": "TV", "kind": "tv", "path": str(nas / "TV"), "default": True},
        {"name": "Music", "kind": "music", "path": str(nas / "Music"), "default": True}]
    harness.services.apply_live(
        Config.model_validate(cfg.model_dump() | {"libraries": libraries}))
    # Named, not found by folder: its Plex folder doesn't contain the filed one.
    harness.web.plex_sections.append({"key": "7", "type": "movie", "title": "Films",
                                      "Location": [{"id": 9, "path": "/volume1/other"}]})
    harness.web.add_film("Example Movie", 1234, "Example Movie", runtime=122)
    _rip(harness)

    _wait_for(harness, DiscStatus.FILED)
    assert extended_path(nas / "Films HD" / FOLDER / f"{FOLDER} - 1080p.mkv").exists()
    assert not (nas / "Movies").exists()
    eventually(lambda: any("/refresh" in r.url.path for r in harness.web.plex_requests))
    scan = next(r for r in harness.web.plex_requests if "/refresh" in r.url.path)
    assert scan.url.path == "/library/sections/7/refresh"
    assert parse_qs(scan.url.query.decode())["path"] == [f"/volume1/media/Films HD/{FOLDER}"]


def test_tmdb_is_searched_with_the_bd_metadata_title_first(harness, client, tmp_path):
    root = tmp_path / "disc"
    (root / "BDMV" / "META" / "DL").mkdir(parents=True)
    (root / "BDMV" / "META" / "DL" / "bdmt_eng.xml").write_text(
        "<di:name>Arrival</di:name>", encoding="utf-8")
    harness.drive.root = root
    harness.web.add_film("Arrival", 329865, "Arrival", runtime=118)
    _rip(harness, label="ARRIVAL_BD")
    rec = _wait_for(harness, DiscStatus.FILED)
    assert rec.title == "Arrival (2016)"
    searches = [r.url.params["query"] for r in harness.web.tmdb_requests
                if r.url.path == "/3/search/movie"]
    # The guess shown while ripping uses only the label; Identification asks title first.
    assert "ARRIVAL" in searches
    assert [q for q in searches if q != "ARRIVAL"][0] == "Arrival"
    assert "tmdb-key" not in "\n".join(map(str, harness.services.discs.log_lines(rec.id)))


def test_runtime_mismatch_and_ambiguous_matches_are_left_for_review_not_encoded(tmp_path):
    h = make_harness(_dir(tmp_path / "a"))
    h.web.add_film("Example Movie", 1, "Example Movie", runtime=95)
    with _client(h):
        _rip(h)
        rec = _wait_for(h, DiscStatus.REVIEW)
        assert rec.review_reason == ReviewReason.RUNTIME_MISMATCH
        saved = json.loads((rec.scratch_dir / "tmdb.json").read_text(encoding="utf-8"))
        assert [c["id"] for c in saved["candidates"]] == [1]  # kept for Review
        assert (rec.scratch_dir / "Example_Movie_t00.mkv").exists()
    assert h.ffmpeg.calls == []

    h = make_harness(_dir(tmp_path / "b"))
    h.web.add_film("Example Movie", 1, "Example Movie", runtime=121)
    h.web.add_film("Example Movie", 2, "Example Movie", runtime=120, year=1987)
    with _client(h) as c:
        _rip(h)
        assert _wait_for(h, DiscStatus.REVIEW).review_reason == ReviewReason.MULTIPLE_MATCHES
        assert "Several films match" in html.unescape(c.get("/").text)  # Needs Review bin
    assert h.ffmpeg.calls == []

    h = make_harness(_dir(tmp_path / "c"))
    with _client(h):
        _rip(h)
        assert _wait_for(h, DiscStatus.REVIEW).review_reason == ReviewReason.NO_MATCH


def _client(h):
    from fastapi.testclient import TestClient

    from ama.app import create_app
    return TestClient(create_app(h.services))


def _dir(path):
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_a_non_english_film_keeps_its_original_language_track(harness, client):
    harness.web.add_film("Example Movie", 1234, "Example Movie", runtime=122,
                         original_language="ja", original_title="例の映画")
    harness.ffmpeg.streams = [
        probe_stream(0, "video", "h264", height=1080),
        probe_stream(1, "audio", "dts", "eng", "Surround 5.1", default=1),
        probe_stream(2, "audio", "truehd", "jpn", "Surround 5.1"),
        probe_stream(3, "audio", "ac3", "fra"),
        probe_stream(4, "subtitle", "hdmv_pgs_subtitle", "eng"),
    ]
    _rip(harness)
    _wait_for(harness, DiscStatus.FILED)
    args = harness.ffmpeg.encodes()[0]
    maps = [args[i + 1] for i, a in enumerate(args) if a == "-map"]
    assert maps == ["0:0", "0:1", "0:2", "0:4"]
    assert args[args.index("-disposition:a:1") + 1] == "default+original"


def test_encodes_run_one_at_a_time_first_in_first_out_with_live_progress(client, harness):
    harness.ffmpeg.hold = True
    harness.web.add_film("Example Movie", 1234, "Example Movie", runtime=122)
    harness.web.add_film("Other Movie", 99, "Other Movie", runtime=122, year=2001)
    _rip(harness)
    eventually(harness.ffmpeg.encoding.is_set)
    eventually(lambda: "40%" in html.unescape(client.get("/").text))
    page = html.unescape(client.get("/").text)
    assert 'sse-swap="encode"' in page and "Example Movie (2016)" in page

    # A second Disc rips while the first Encode runs, and waits its turn.
    harness.makemkv.disc_name = "Other Movie"
    harness.drive.insert(DiscType.BD, "OTHER_MOVIE")
    eventually(lambda: harness.drive.ejected == 2)
    movies = harness.services.movie_archive.movies
    eventually(lambda: movies.get(2) is not None)
    assert movies.get(1).status == EncodeStatus.ENCODING
    assert movies.get(2).status == EncodeStatus.QUEUED
    assert len(harness.ffmpeg.encodes()) == 1
    assert "Next in line" in html.unescape(client.get("/").text)

    harness.ffmpeg.release()
    eventually(lambda: len(harness.services.discs.list(DiscStatus.FILED)) == 2, timeout=5)
    encoded = [c[c.index("-i") + 1] for c in harness.ffmpeg.encodes()]
    # Each Disc's Main Feature and Extra, the first Disc's first.
    assert ["/1/" in p.replace("\\", "/") for p in encoded] == [True, True, False, False]


def test_a_rip_runs_while_an_encode_is_in_progress(client, harness):
    harness.ffmpeg.hold = True
    harness.web.add_film("Example Movie", 1234, "Example Movie", runtime=122)
    _rip(harness)
    eventually(harness.ffmpeg.encoding.is_set)
    harness.makemkv.ripped_ids.clear()
    harness.drive.insert(DiscType.DVD, "SOMETHING_ELSE")
    eventually(lambda: harness.drive.ejected == 2)
    assert harness.makemkv.ripped_ids == [0, 1]  # ripped while the Encode was still going
    assert harness.ffmpeg.encoding.is_set()
    harness.ffmpeg.release()


def test_a_failed_encode_keeps_the_rip_and_is_retried_after_a_restart(tmp_path):
    h = make_harness(tmp_path)
    h.ffmpeg.exit_code = 1
    h.web.add_film("Example Movie", 1234, "Example Movie", runtime=122)
    with _client(h):
        _rip(h)
        eventually(lambda: (m := h.services.movie_archive.movies.get(1)) is not None
                   and m.status == EncodeStatus.FAILED)
        rec = h.services.discs.get(1)
        assert rec.status == DiscStatus.RIPPED
        assert (rec.scratch_dir / "Example_Movie_t00.mkv").exists()
        log = "\n".join(map(str, h.services.discs.log_lines(1)))
        assert "OpenEncodeSessionEx failed" in log and "The Encode didn't work" in log

    # Restart with ffmpeg fixed: the Encode is tried again and filed.
    h2 = make_harness(tmp_path)
    h2.web.add_film("Example Movie", 1234, "Example Movie", runtime=122)
    with _client(h2):
        _wait_for(h2, DiscStatus.FILED)


def test_an_encode_waits_for_the_nas_then_files(tmp_path):
    h = make_harness(tmp_path, nas_reachable=False)
    h.web.add_film("Example Movie", 1234, "Example Movie", runtime=122)
    with _client(h):
        _rip(h)
        eventually(lambda: (m := h.services.movie_archive.movies.get(1)) is not None
                   and m.status == EncodeStatus.ENCODED)
        assert h.services.discs.get(1).status == DiscStatus.RIPPED
        h.share["reachable"] = True
        _wait_for(h, DiscStatus.FILED)
    # filed from the finished Encodes (Main Feature + Extra), not re-encoded
    assert len(h.ffmpeg.encodes()) == 2


def _picture_sample(name: str) -> list[str]:
    path = Path(__file__).parent / "data" / "ffmpeg" / f"sample-{name}.txt"
    return path.read_text(encoding="utf-8").splitlines()


def _dvd_video(**extra) -> dict:
    return probe_stream(0, "video", "mpeg2video", width=720, height=480,
                        r_frame_rate="30000/1001", **extra)


@pytest.mark.parametrize("sample, vf, said", [
    ("telecined", "fieldmatch=order=tff:combmatch=full,"
                  "bwdif=mode=send_frame:parity=auto:deint=interlaced,decimate,crop=720:360:0:60",
     "telecined film (TFF), detelecined to film rate; cropped 720x480 to 720x360 at 0,60"),
    ("interlaced", "bwdif=mode=send_field:parity=auto:deint=all",
     "interlaced (TFF), deinterlaced to one frame per field; no black bars to crop"),
])
def test_a_dvd_is_encoded_progressive_and_cropped(client, harness, sample, vf, said):
    harness.ffmpeg.streams[0] = _dvd_video()
    harness.ffmpeg.sample_output = _picture_sample(sample)
    harness.web.add_film("Example Movie", 1234, "Example Movie", runtime=122)
    _rip(harness, disc_type=DiscType.DVD)

    rec = _wait_for(harness, DiscStatus.FILED)
    runs = harness.ffmpeg.samples()
    # 10 for the Main Feature, 10 for its Extra
    assert len(runs) == 20 and all(r[r.index("-vf") + 1].startswith("idet,") for r in runs)
    encode = harness.ffmpeg.encodes()[0]
    assert encode[encode.index("-vf") + 1] == vf
    log = "\n".join(map(str, harness.services.discs.log_lines(rec.id)))
    assert f"Picture: {said}" in log


def test_a_letterboxed_bd_is_cropped_without_scan_detection(client, harness):
    harness.ffmpeg.sample_output = [
        "[Parsed_cropdetect_0 @ 0000] x1:0 x2:1919 y1:140 y2:939 w:1920 h:800 x:0 y:140 "
        "pts:1 t:1.0 limit:0.100000 crop=1920:800:0:140"]
    harness.ffmpeg.streams[0] = probe_stream(0, "video", "h264", width=1920, height=1080,
                                             r_frame_rate="24000/1001")
    harness.web.add_film("Example Movie", 1234, "Example Movie", runtime=122)
    _rip(harness)

    _wait_for(harness, DiscStatus.FILED)
    assert all("idet" not in r[r.index("-vf") + 1] for r in harness.ffmpeg.samples())
    encode = harness.ffmpeg.encodes()[0]
    assert encode[encode.index("-vf") + 1] == "crop=1920:800:0:140"


def test_a_film_with_no_bars_and_nothing_to_fix_gets_no_video_filter(client, harness):
    harness.web.add_film("Example Movie", 1234, "Example Movie", runtime=122)
    _rip(harness)
    _wait_for(harness, DiscStatus.FILED)
    assert "-vf" not in harness.ffmpeg.encodes()[0]


def test_a_uhd_is_encoded_keeping_its_hdr10_metadata_checked_and_filed_as_the_4k_version(
        client, harness):
    _uhd_source(harness)
    harness.web.add_film("Example Movie", 1234, "Example Movie", runtime=122)
    _rip(harness, disc_type=DiscType.UHD)

    rec = _wait_for(harness, DiscStatus.FILED)
    assert _filed(harness, "4K").exists()
    args = harness.ffmpeg.encodes()[0]
    line = " ".join(args)
    assert args[args.index("-cq") + 1] == "24"  # UHD's CQ
    assert "-profile:v main10" in line
    assert ("-color_primaries bt2020 -color_trc smpte2084 -colorspace bt2020nc "
            "-color_range tv") in line
    probed = [c[-1] for c in harness.ffmpeg.calls if "-show_frames" in c]
    assert any(p.endswith("encode.tmp.mkv") for p in probed)  # the finished Encode was checked
    log = "\n".join(map(str, harness.services.discs.log_lines(rec.id)))
    assert "HDR10 metadata kept: 0.005-1000 nits" in log and "MaxCLL 1000, MaxFALL 400" in log


def test_an_encode_that_loses_the_hdr10_metadata_fails_and_keeps_the_rip(harness, client):
    _uhd_source(harness)
    harness.ffmpeg.encode_frame = {**HDR10_FRAME, "side_data_list": []}
    harness.web.add_film("Example Movie", 1234, "Example Movie", runtime=122)
    _rip(harness, disc_type=DiscType.UHD)

    movies = harness.services.movie_archive.movies
    eventually(lambda: (m := movies.get(1)) is not None and m.status == EncodeStatus.FAILED)
    rec = harness.services.discs.get(1)
    assert rec.status == DiscStatus.RIPPED
    assert (rec.scratch_dir / "Example_Movie_t00.mkv").exists()
    assert not (rec.scratch_dir / "encode.tmp.mkv").exists()
    assert not (rec.scratch_dir / "encode.mkv").exists()
    log = "\n".join(map(str, harness.services.discs.log_lines(1)))
    assert "the mastering display metadata is missing" in log
    assert "MaxCLL is missing, not 1000" in log


def test_the_bd_and_uhd_of_one_film_are_filed_into_one_folder_as_two_versions(client, harness):
    harness.web.add_film("Example Movie", 1234, "Example Movie", runtime=122)
    _rip(harness)
    eventually(lambda: len(harness.services.discs.list(DiscStatus.FILED)) == 1, timeout=5)

    _uhd_source(harness)
    harness.drive.insert(DiscType.UHD, "EXAMPLE_MOVIE_UHD")
    eventually(lambda: len(harness.services.discs.list(DiscStatus.FILED)) == 2, timeout=5)

    folder = extended_path(harness.nas_root / "Movies" / FOLDER)
    assert sorted(p.name for p in folder.iterdir()) == [
        f"{FOLDER} - 1080p.mkv", f"{FOLDER} - 4K.mkv", "Other"]
    # Both Discs' Extras are kept, each named after its Disc.
    assert sorted(p.name for p in (folder / "Other").iterdir()) == [
        "EXAMPLE_MOVIE - Title 2.mkv", "EXAMPLE_MOVIE_UHD - Title 2.mkv"]
    filed = harness.services.discs.list(DiscStatus.FILED)
    assert filed[0].archive_dir == filed[1].archive_dir


def test_a_4k_main_feature_is_encoded_as_uhd_even_if_the_disc_looked_like_a_blu_ray(
        client, harness):
    _uhd_source(harness)
    harness.web.add_film("Example Movie", 1234, "Example Movie", runtime=122)
    _rip(harness, disc_type=DiscType.BD)
    rec = _wait_for(harness, DiscStatus.FILED)
    assert _filed(harness, "4K").exists()
    args = harness.ffmpeg.encodes()[0]
    assert args[args.index("-cq") + 1] == "24"
    log = "\n".join(map(str, harness.services.discs.log_lines(rec.id)))
    assert "its Main Feature is 4K, so it is encoded as a UHD" in log
