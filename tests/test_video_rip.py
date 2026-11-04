"""Video Rip to scratch: insert a DVD/BD, every Title >= 30 s is ripped, the Disc ejects."""

import html
import time
from pathlib import Path

from ama.drive import DiscType
from tests.conftest import eventually


def page_text(client, url: str) -> str:
    return html.unescape(client.get(url).text)


def ripped_files(harness) -> list[str]:
    root = Path(harness.services.config.paths.scratch) / "video"
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*.mkv"))


def test_all_long_titles_are_ripped_to_scratch_and_the_disc_ejects(client, harness):
    harness.makemkv.release()
    harness.drive.insert(DiscType.BD, "EXAMPLE_MOVIE")
    eventually(lambda: harness.drive.ejected == 1)
    # Title 2 repeats Title 0's segments; Title 3 is 12 s long.
    assert ripped_files(harness) == ["1/Example_Movie_t00.mkv", "1/Example_Movie_t01.mkv"]
    assert harness.makemkv.ripped_ids == [0, 1]
    page = page_text(client, "/discs/1")
    assert "EXAMPLE_MOVIE" in page and "Ripped" in page
    assert "2:01:33" in page and "0:02:31" in page
    assert "33.5 GB" in page
    # 11 dropped by MakeMKV's --minlength + Title 3; 1 dropped by MakeMKV + Title 2.
    assert "12 Titles shorter than 30 seconds" in page
    assert "2 exact duplicates" in page


def test_rip_progress_is_shown_while_ripping(client, harness):
    harness.drive.insert(DiscType.DVD, "HEAT_DISC1")
    eventually(lambda: "Title 1 of 2" in page_text(client, "/disc"))
    page = page_text(client, "/disc")
    assert 'sse-swap="rip"' in page
    assert "Ripping 50%" in page and "Waiting" in page
    assert "Ripping" in page_text(client, "/")  # the drive card on Now
    harness.makemkv.release()
    eventually(lambda: harness.drive.ejected == 1)
    assert "Title 1 of 2" not in page_text(client, "/disc")


def test_rip_progress_is_pushed_live_over_sse(live_server, harness):
    import httpx

    from tests.test_web_now import _read_event

    with httpx.stream("GET", f"{live_server}/events", timeout=5) as r:
        lines = r.iter_lines()
        assert "Nothing is being ripped" in _read_event(lines, "rip")
        harness.drive.insert(DiscType.BD, "EXAMPLE_MOVIE")
        while "Ripping 50%" not in (fragment := html.unescape(_read_event(lines, "rip"))):
            pass
        assert "Title 1 of 2" in fragment
        harness.makemkv.release()
        while "Disc ejected at" not in _read_event(lines, "rip"):
            pass


def test_licence_error_is_a_hard_stop_shown_as_a_makemkv_problem(client, harness):
    harness.makemkv.licence_ok = False
    harness.drive.insert(DiscType.BD, "MATRIX_BD")
    eventually(lambda: harness.drive.ejected == 1)
    assert len(harness.makemkv.calls) == 1  # nothing else is attempted
    eventually(lambda: "licence key isn't valid" in page_text(client, "/"))
    page = page_text(client, "/discs/1")
    assert "licence key isn't valid" in page and "MATRIX_BD" in page
    assert "This isn't a problem with the Disc" in page
    assert "too old" in client.get("/discs/1/log").text
    assert ripped_files(harness) == []


def test_a_uhd_rips_in_libredrive_mode(client, harness):
    harness.makemkv.release()
    harness.drive.insert(DiscType.UHD, "EXAMPLE_MOVIE_UHD")
    eventually(lambda: harness.drive.ejected == 1)
    assert ripped_files(harness) == ["1/Example_Movie_t00.mkv", "1/Example_Movie_t01.mkv"]
    log = client.get("/discs/1/log").text
    assert "Using LibreDrive mode" in log
    assert "Ripped" in page_text(client, "/discs/1")


def test_a_uhd_the_drive_wont_open_without_libredrive_is_scanned_once_more(client, harness):
    harness.makemkv.libredrive_refusals = 1  # e.g. the drive just reset its LibreDrive mode
    harness.makemkv.release()
    harness.drive.insert(DiscType.UHD, "EXAMPLE_MOVIE_UHD")
    eventually(lambda: harness.drive.ejected == 1)
    assert ripped_files(harness) == ["1/Example_Movie_t00.mkv", "1/Example_Movie_t01.mkv"]
    log = client.get("/discs/1/log").text
    assert "LibreDrive compatible drive is required" in log
    assert "Reading the Disc once more" in log


def test_a_uhd_that_needs_libredrive_fails_with_advice_and_ejects(client, harness):
    harness.makemkv.libredrive_refusals = 2
    harness.drive.insert(DiscType.UHD, "EXAMPLE_MOVIE_UHD")
    eventually(lambda: harness.drive.ejected == 1)
    assert not any("mkv" in c for c in harness.makemkv.calls)  # nothing ripped
    assert ripped_files(harness) == []
    page = page_text(client, "/discs/1")
    assert "can't decrypt this UHD Blu-ray" in page
    assert "LibreDrive" in page and "Open MakeMKV" in page


def test_failed_rip_ejects_deletes_partial_files_and_keeps_the_log(client, harness):
    harness.makemkv.fail_title = 1
    harness.makemkv.release()
    harness.drive.insert(DiscType.BD, "EXAMPLE_MOVIE")
    eventually(lambda: harness.drive.ejected == 1)
    eventually(lambda: "Couldn't rip" in page_text(client, "/"))
    assert ripped_files(harness) == []
    assert not (Path(harness.services.config.paths.scratch) / "video" / "1").exists()
    page = page_text(client, "/discs/1")
    assert "Failed" in page and "Title 2 couldn't be ripped" in page
    assert "Error 'Scsi error - MEDIUM ERROR' occurred while reading" in page  # the log
    assert "Scsi error" in client.get("/discs/1/log").text

    # No auto-retry: reinserting is up to the person, and dismissing clears the notice.
    calls = len(harness.makemkv.calls)
    time.sleep(0.2)  # many drive polls
    assert len(harness.makemkv.calls) == calls
    client.post("/discs/1/dismiss")
    assert "Couldn't rip" not in page_text(client, "/")


def test_a_rip_interrupted_by_a_restart_is_failed_not_retried(tmp_path):
    from fastapi.testclient import TestClient

    from ama.app import create_app
    from tests.conftest import make_harness

    h = make_harness(tmp_path)
    with TestClient(create_app(h.services)):
        h.drive.insert(DiscType.BD, "EXAMPLE_MOVIE")
        eventually(lambda: h.makemkv.ripping)
    partial = Path(h.services.config.paths.scratch) / "video" / "1"
    assert partial.exists()

    h2 = make_harness(tmp_path)
    h2.drive.insert(DiscType.BD, "EXAMPLE_MOVIE")
    with TestClient(create_app(h2.services)) as client:
        eventually(lambda: h2.drive.ejected == 1)
        page = page_text(client, "/discs/1")
        assert "Failed" in page and "stopped during the Rip" in page
        assert not partial.exists()
        assert h2.makemkv.calls == []


def test_a_disc_identified_before_the_tray_opens_still_shows_as_ripped(client, harness,
                                                                       monkeypatch):
    from ama.discs import DiscStatus

    eject = harness.drive.eject

    def slow_eject() -> None:  # the tray takes longer than Identification
        eventually(lambda: harness.services.discs.list(DiscStatus.REVIEW))
        eject()

    monkeypatch.setattr(harness.drive, "eject", slow_eject)
    harness.makemkv.release()
    harness.drive.insert(DiscType.BD, "EXAMPLE_MOVIE")  # TMDB doesn't know it: Review
    eventually(lambda: harness.drive.ejected == 1)
    eventually(lambda: harness.services.video_rip.progress is None)
    page = page_text(client, "/disc")
    assert "Disc ejected at" in page and "See what went wrong" not in page


def test_while_ripping_a_likely_film_is_guessed_from_the_volume_label(client, harness):
    harness.web.add_film("Heat", 949, "Heat", runtime=170, year=1995, poster_path="/heat.jpg")
    harness.web.tmdb_images["/heat.jpg"] = b"\xff\xd8 heat poster"
    harness.drive.insert(DiscType.DVD, "HEAT_DISC1")
    eventually(lambda: "Likely" in page_text(client, "/"))
    for page in (page_text(client, "/"), page_text(client, "/disc")):
        assert "Heat (1995)" in page and "from the Disc label" in page
        assert '<img src="/covers/tmdb-movie-949.jpg" alt="Poster of Heat (1995)">' in page
        assert "HEAT_DISC1" in page  # still says which Disc it is
    assert client.get("/covers/tmdb-movie-949.jpg").content == b"\xff\xd8 heat poster"
    harness.makemkv.release()
    eventually(lambda: harness.drive.ejected == 1)


def test_a_film_guess_tmdb_cant_give_is_left_out_quietly(client, harness):
    harness.web.tmdb_offline = True
    harness.drive.insert(DiscType.DVD, "HEAT_DISC1")
    eventually(lambda: "Title 1 of 2" in page_text(client, "/disc"))
    eventually(lambda: harness.web.tmdb_requests)
    assert "Likely" not in page_text(client, "/disc") and "TMDB" not in page_text(client, "/disc")
    harness.makemkv.release()
    eventually(lambda: harness.drive.ejected == 1)
