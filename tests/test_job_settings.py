"""Per-Job settings (#30): overrides of ama.toml for one Job, each group locked at its
Phase start with the values it was locked with stored on the Job."""

from __future__ import annotations

import pytest

from ama.config import Config, Kind
from ama.drive import DiscType
from ama.job_settings import Group, Locked
from tests.conftest import make_harness


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
    nas = h.nas_root
    cfg = h.services.config
    h.services.apply_live(Config.model_validate(cfg.model_dump() | {"libraries": [
        {"name": "Movies", "kind": "films", "path": str(nas / "Movies"), "default": True},
        {"name": "Family Films", "kind": "films", "path": str(nas / "Family")},
        {"name": "TV", "kind": "tv", "path": str(nas / "TV"), "default": True},
        {"name": "Music", "kind": "music", "path": str(nas / "Music"), "default": True}]}))
    job = _job(h)
    settings = h.services.job_settings
    settings.set(job.id, "library", "Family Films")

    assert settings.library(job, Kind.FILMS) == "Family Films"
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
