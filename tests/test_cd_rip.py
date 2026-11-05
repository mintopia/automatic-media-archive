"""CD Rip end to end: the real app with a fake drive and a fake cyanrip process."""

from __future__ import annotations

import time

from ama.cdrip import NOT_INSTALLED
from ama.jobs import JobStatus
from ama.drive import DiscType
from tests.conftest import eventually


def _only_disc(harness, status: JobStatus):
    eventually(lambda: len(harness.services.jobs.list(status)) == 1)
    return harness.services.jobs.list(status)[0]


def _rip_calls(harness) -> list[list[str]]:
    return [c for c in harness.cyanrip.calls if "-I" not in c]


def test_inserted_cd_is_ripped_to_scratch_verified_and_ejected(harness, client):
    harness.cyanrip.ar_confidence = {1: 12, 2: 11, 3: 7}
    harness.drive.insert(DiscType.CD)

    rec = _only_disc(harness, JobStatus.RIPPED)
    files = sorted(p.name for p in rec.scratch_dir.iterdir())
    assert files == ["01.flac", "02.flac", "03.flac", "rip.cue", "rip.log"]
    assert rec.scratch_dir.parent == harness.services.config.paths.scratch / "cd"
    assert harness.drive.ejected == 1

    page = client.get(f"/jobs/{rec.id}").text
    assert "matches 12 other rips" in page
    assert "matches 7 other rips" in page
    assert "3 of 3 tracks verified" in page
    assert "waiting to be identified" in client.get("/").text


def test_rip_is_secure_and_keeps_pre_emphasis_and_hidden_track(harness, client):
    harness.drive.insert(DiscType.CD)
    _only_disc(harness, JobStatus.RIPPED)
    rip = _rip_calls(harness)[0]
    assert rip[rip.index("-P") + 1] == "3"            # cdparanoia full checking
    assert "-W" in rip                                 # never de-emphasise
    assert rip[rip.index("-p") + 1] == "1=track"       # hidden track -> track 0
    assert rip[rip.index("-s") + 1] == "667"           # drive offset from config
    assert rip[rip.index("-d") + 1] == "D:"
    assert "-A" not in rip                             # AccurateRip stays on


def test_tracks_not_matching_accuraterip_are_shown_unverified(harness, client):
    harness.cyanrip.ar_confidence = {1: 12}
    harness.drive.insert(DiscType.CD)
    rec = _only_disc(harness, JobStatus.RIPPED)
    page = client.get(f"/jobs/{rec.id}").text
    assert page.count("Doesn't match other rips") == 2
    assert "1 of 3 tracks verified" in page


def test_cd_missing_from_accuraterip(harness, client):
    harness.cyanrip.in_accuraterip = False
    harness.drive.insert(DiscType.CD)
    rec = _only_disc(harness, JobStatus.RIPPED)
    assert client.get(f"/jobs/{rec.id}").text.count("no other rips to compare") == 3


def test_progress_is_live_per_track(harness, client):
    harness.cyanrip.ar_confidence = {1: 12}
    harness.cyanrip.hold_at = 2
    harness.drive.insert(DiscType.CD)
    harness.cyanrip.wait_until_held()
    eventually(lambda: harness.services.cd.current is not None
               and harness.services.cd.current.tracks[1].percent == 50.0)
    cd = harness.services.cd.current
    page = client.get(f"/jobs/{cd.job_id}").text
    assert "Track 2 of 3" in page
    assert "Ripping 50%" in page
    assert "matches 12 other rips" in page  # track 1 already done
    assert 'role="progressbar" aria-valuenow="50"' in page
    assert page[:page.index('id="steps"')].count("Waiting") == 1  # track 3 (not the Steps)
    # 200 s done + half of 100 s, of 600 s
    assert round(cd.percent) == 42
    assert "Track 2 of 3 · 41%" in client.get("/").text
    harness.cyanrip.release()
    _only_disc(harness, JobStatus.RIPPED)


def test_progress_is_pushed_live_over_sse(live_server, harness):
    import httpx

    harness.cyanrip.hold_at = 2
    latest: dict[str, str] = {}
    with httpx.stream("GET", f"{live_server}/events", timeout=5) as r:
        harness.drive.insert(DiscType.CD)
        harness.cyanrip.wait_until_held()
        event = None
        for line in r.iter_lines():
            if line.startswith("event: "):
                event, latest[line[7:]] = line[7:], ""
            elif line.startswith("data: ") and event:
                latest[event] += line[6:] + "\n"
            if "Ripping 50%" in latest.get("cd-rip", "") and \
                    "Track 2 of 3 · 41%" in latest.get("ripping", "") and \
                    "Track 2 of 3" in latest.get("drive", ""):
                break
        harness.cyanrip.release()


def test_hidden_track_and_pre_emphasis_are_reported(harness, client):
    harness.cyanrip.tracks = [(0, 38.0), (1, 284.0), (2, 100.0)]
    harness.cyanrip.preemphasis = {1, 2}
    harness.drive.insert(DiscType.CD)
    rec = _only_disc(harness, JobStatus.RIPPED)
    assert (rec.scratch_dir / "00.flac").exists()
    page = client.get(f"/jobs/{rec.id}").text
    assert "Hidden track before track 1" in page
    assert "0:38 of audio before track 1" in page
    assert "mastered with pre-emphasis" in page


def test_enhanced_cd_shown_as_unrecognised_is_ripped_without_its_data_track(harness, client):
    harness.cyanrip.enhanced_cd = True
    harness.cyanrip.data_track = 4
    harness.drive.insert_unrecognised("ENHANCED")
    rec = _only_disc(harness, JobStatus.RIPPED)
    cue = (rec.scratch_dir / "rip.cue").read_text(encoding="utf-8")
    assert "BINARY" not in cue and "TRACK 04" not in cue
    assert "TRACK 03 AUDIO" in cue
    assert not (rec.scratch_dir / "04.flac").exists()


def test_data_disc_is_left_alone(harness, client):
    harness.drive.insert_unrecognised("BACKUP_2019")
    eventually(lambda: len(harness.cyanrip.calls) == 1)
    assert _rip_calls(harness) == []
    assert harness.services.jobs.list(JobStatus.FAILED) == []
    assert harness.drive.ejected == 0


def test_unreadable_track_fails_ejects_deletes_partial_files_and_shows_log(harness, client):
    harness.cyanrip.read_errors_in = 2
    harness.drive.insert(DiscType.CD)
    rec = _only_disc(harness, JobStatus.FAILED)
    assert rec.failure.headline == "Track 2 couldn't be read cleanly, even after 10 tries."
    assert not rec.scratch_dir.exists()
    assert harness.drive.ejected == 1

    page = client.get(f"/jobs/{rec.id}").text
    assert "Couldn't read this CD" in page
    assert "Unknown CD · 3 tracks" in page
    assert "Ripping errors: 3" in page                      # cyanrip's own log
    assert '<span class="e">' in page                         # errors highlighted
    assert "Disc ejected" in page
    now = client.get("/").text
    assert "Didn't work" in now and f'href="/jobs/{rec.id}"' in now


def test_failed_rip_is_not_retried(harness, client):
    harness.cyanrip.read_errors_in = 1
    harness.drive.stuck = True  # the Disc stays in after the failure
    harness.drive.insert(DiscType.CD)
    rec = _only_disc(harness, JobStatus.FAILED)
    time.sleep(0.3)  # many drive polls
    assert len(_rip_calls(harness)) == 1
    assert "eject the Disc: The tray is stuck" in client.get(f"/jobs/{rec.id}").text


def test_dismissing_a_failure_clears_it_from_now(harness, client):
    harness.cyanrip.no_disc = True
    harness.drive.insert(DiscType.CD)
    rec = _only_disc(harness, JobStatus.FAILED)
    assert rec.failure.kind == "drive"
    r = client.post(f"/jobs/{rec.id}/dismiss", follow_redirects=False)
    assert r.status_code == 303
    assert "Didn't work" not in client.get("/").text
    assert "Couldn't rip this CD" in client.get(f"/jobs/{rec.id}").text  # still viewable


def test_missing_cyanrip_is_a_failure_with_a_fix(harness, client):
    harness.cyanrip.installed = False
    harness.drive.insert(DiscType.CD)
    rec = _only_disc(harness, JobStatus.FAILED)
    assert rec.failure == NOT_INSTALLED
    assert harness.drive.ejected == 1


def test_rip_cut_off_by_a_restart_is_failed_and_cleaned_up(harness):
    jobs = harness.services.jobs
    rec = jobs.create(DiscType.CD, "", "cd")
    rec.scratch_dir.mkdir(parents=True)
    (rec.scratch_dir / "01.flac").write_bytes(b"partial")
    harness.services.cd.recover()
    harness.services.cd.recover()  # idempotent
    failed = jobs.get(rec.id)
    assert failed.status == JobStatus.FAILED
    assert failed.failure.kind == "interrupted"
    assert not rec.scratch_dir.exists()


def test_cd_tool_path_comes_from_the_tool_lookup(tmp_path):
    from ama.app import build_services
    from tests.conftest import make_config
    from tests.fakes import FakeCyanrip, FakeDrive

    drive = FakeDrive()
    fake = FakeCyanrip(drive)
    services = build_services(make_config(tmp_path), probe=drive, streamer=fake,
                              nas_exists=lambda p: True,
                              tool=lambda name: tmp_path / "tools" / f"{name}.exe")
    import asyncio
    drive.insert(DiscType.CD)

    async def go():
        await services.drive.poll_once()
        await services.cd.check_once()

    asyncio.run(go())
    assert fake.calls[0][0] == str(tmp_path / "tools" / "cyanrip.exe")


def test_a_cd_swapped_in_between_two_looks_is_still_ripped(harness):
    """The ripper may not look at the drive while it is empty (busy box, fast swap):
    the next CD is a new insertion all the same, even under the same label."""
    import asyncio

    async def go():
        harness.drive.insert(DiscType.CD, "SAME")
        await harness.services.drive.poll_once()
        await harness.services.cd.check_once()  # rips, ejects: the drive reads empty
        harness.cyanrip.mb_disc_id = "O75dAncJZ7onpacHCAgF4NqupdA-"  # another CD (same: a repeat)
        harness.drive.insert(DiscType.CD, "SAME")
        await harness.services.drive.poll_once()  # the ripper never saw it empty
        await harness.services.cd.check_once()

    asyncio.run(go())
    assert len(_rip_calls(harness)) == 2
    assert len(harness.services.jobs.list(JobStatus.RIPPED)) == 2


def _info(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelname == "INFO"]


def test_a_rip_starting_and_finishing_is_logged(harness, client, caplog):
    caplog.set_level("INFO")
    harness.drive.insert(DiscType.CD, "OK_COMPUTER")
    rec = _only_disc(harness, JobStatus.RIPPED)
    assert f"Rip started: Audio CD “OK_COMPUTER” (Job {rec.id})" in _info(caplog)
    eventually(lambda: f"Rip finished: Audio CD “OK_COMPUTER” (Job {rec.id}): ripped"
               in _info(caplog))
