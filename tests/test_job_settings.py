"""Per-Job settings (#30): overrides of ama.toml for one Job, each group locked at its
Phase start with the values it was locked with stored on the Job."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ama.app import create_app
from ama.archive import extended_path
from ama.config import Config, LibraryKind
from ama.drive import DiscType
from ama.job_settings import Group, Locked
from ama.jobs import JobStatus
from tests.conftest import eventually, make_harness


@pytest.fixture
def h(tmp_path):
    return make_harness(tmp_path)


def _job(h, disc_type=DiscType.BD):
    return h.services.jobs.create(disc_type, "EXAMPLE", "cd" if disc_type == DiscType.CD
                                  else "video")


def _edit_encode(h, **changes) -> None:
    cfg = h.services.config
    h.services.apply_live(cfg.model_copy(update={"encode": cfg.encode.model_copy(update=changes)}))


def test_an_override_applies_to_its_job_only(h):
    a, b = _job(h), _job(h)
    h.services.job_settings.set(a.id, "encode.quality", "19")

    assert h.services.job_settings.encode_config(a).cq.bd == 19
    assert h.services.job_settings.encode_config(b).cq.bd == 22  # ama.toml's BD quality


def test_unoverridden_values_follow_a_global_change_until_the_group_locks(h):
    following, overridden, locked = _job(h), _job(h), _job(h)
    settings = h.services.job_settings
    settings.set(overridden.id, "encode.speed", "faster")
    settings.encode_config(locked)  # its Encode started: the Encode group locks

    _edit_encode(h, speed="slowest", audio="all")

    assert settings.encode_config(following).speed == "slowest"
    assert settings.encode_config(following).audio == "all"
    assert settings.encode_config(overridden).speed == "faster"  # the override wins
    assert settings.encode_config(overridden).audio == "all"
    assert settings.encode_config(locked).speed == "slower"  # as it was when it locked
    assert settings.encode_config(locked).audio == "languages"


def test_a_locked_group_rejects_edits_and_keeps_its_snapshot(h):
    job = _job(h)
    settings = h.services.job_settings
    settings.set(job.id, "encode.quality", "20")
    settings.encode_config(job)

    with pytest.raises(Locked) as refused:
        settings.set(job.id, "encode.quality", "18")
    assert refused.value.group == Group.ENCODE
    with pytest.raises(Locked):
        settings.reset(job.id, "encode.quality")
    assert settings.encode_config(job).cq.bd == 20
    # The other groups are still open.
    settings.set(job.id, "library", "Movies")


def test_choosing_the_default_value_is_no_override(h):
    job = _job(h)
    settings = h.services.job_settings
    settings.set(job.id, "encode.speed", "faster")
    settings.set(job.id, "encode.speed", "slower")  # ama.toml's speed
    _edit_encode(h, speed="balanced")
    assert settings.encode_config(job).speed == "balanced"


def test_a_value_that_isnt_offered_is_refused(h):
    job = _job(h)
    settings = h.services.job_settings
    with pytest.raises(ValueError):
        settings.set(job.id, "encode.speed", "ludicrous")
    with pytest.raises(ValueError):
        settings.set(job.id, "encode.quality", "60")
    with pytest.raises(ValueError):
        settings.set(job.id, "library", "Nowhere")
    with pytest.raises(ValueError):
        settings.set(job.id, "cd.offset", "6")  # a video Job has no Rip settings


def test_the_library_pick_locks_when_filing_starts(h):
    root = h.libraries_root
    cfg = h.services.config
    h.services.apply_live(Config.model_validate(cfg.model_dump() | {"libraries": [
        {"name": "Movies", "kind": "films", "path": str(root / "Movies"), "default": True},
        {"name": "Family Films", "kind": "films", "path": str(root / "Family")},
        {"name": "TV", "kind": "tv", "path": str(root / "TV"), "default": True},
        {"name": "Music", "kind": "music", "path": str(root / "Music"), "default": True}]}))
    job = _job(h)
    settings = h.services.job_settings
    settings.set(job.id, "library", "Family Films")

    assert settings.library(job, LibraryKind.FILMS) == "Family Films"
    with pytest.raises(Locked) as refused:
        settings.set(job.id, "library", "Movies")
    assert refused.value.group == Group.LIBRARY
    assert settings.locked_at(job.id, Group.IDENTIFICATION) is not None  # locked with it


def test_a_cd_job_locks_its_rip_settings_at_once(h):
    job = _job(h, DiscType.CD)
    settings = h.services.job_settings
    rip = settings.rip_config(job)
    assert (rip.offset, rip.retries) == (667, 10)
    with pytest.raises(Locked):
        settings.set(job.id, "cd.retries", "4")


# -- through the pipeline ------------------------------------------------------

FOLDER = "Example Movie (2016) {tmdb-1234}"


def _family_films(h) -> None:
    root = h.libraries_root
    cfg = h.services.config
    h.services.apply_live(Config.model_validate(cfg.model_dump() | {"libraries": [
        {"name": "Movies", "kind": "films", "path": str(root / "Movies"), "default": True},
        {"name": "Family Films", "kind": "films", "path": str(root / "Family")},
        {"name": "TV", "kind": "tv", "path": str(root / "TV"), "default": True},
        {"name": "Music", "kind": "music", "path": str(root / "Music"), "default": True}]}))


def test_a_film_job_encodes_and_files_with_the_settings_changed_while_it_ripped(tmp_path):
    h = make_harness(tmp_path)
    _family_films(h)
    h.web.add_film("Example Movie", 1234, "Example Movie", runtime=122)
    settings = h.services.job_settings
    with TestClient(create_app(h.services)):
        h.drive.insert(DiscType.BD, "EXAMPLE_MOVIE")
        eventually(lambda: h.services.jobs.list(JobStatus.RIPPING))
        job = h.services.jobs.list(JobStatus.RIPPING)[0]
        settings.set(job.id, "encode.quality", "19")
        settings.set(job.id, "library", "Family Films")
        h.ffmpeg.hold = True
        h.makemkv.release()
        eventually(h.ffmpeg.encoding.is_set)
        _edit_encode(h, speed="faster")  # after the Encode began: not this Job's
        with pytest.raises(Locked):
            settings.set(job.id, "encode.quality", "18")
        h.ffmpeg.release()
        eventually(lambda: h.services.jobs.list(JobStatus.FILED), timeout=5)
    encodes = h.ffmpeg.encodes()
    assert len(encodes) == 2  # the Main Feature and its Extra
    for args in encodes:
        assert args[args.index("-cq") + 1] == "19"
        assert args[args.index("-preset") + 1] == "p7"  # "slower", as when it locked
    assert extended_path(h.libraries_root / "Family" / FOLDER / f"{FOLDER} - 1080p.mkv").exists()
    stored = settings.group(job, Group.LIBRARY)
    assert stored.locked and stored.values[0].value == "Family Films"


def test_a_cd_rips_with_the_rip_settings_it_locked(tmp_path):
    h = make_harness(tmp_path)
    with TestClient(create_app(h.services)):
        h.drive.insert(DiscType.CD)
        eventually(lambda: h.services.jobs.list(JobStatus.RIPPED))
    job = h.services.jobs.list(JobStatus.RIPPED)[0]
    rip = h.services.job_settings.group(job, Group.RIP)
    assert rip.locked
    assert [(v.setting.label, v.text) for v in rip.values] == [
        ("Drive read offset", "+667 samples"), ("Re-reads before an error", "10")]
