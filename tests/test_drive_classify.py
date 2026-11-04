from pathlib import Path

import pytest

from ama.drive import DiscType, classify_root


def _bdmv(root: Path, version: bytes) -> None:
    (root / "BDMV").mkdir()
    (root / "BDMV" / "index.bdmv").write_bytes(b"INDX" + version + b"\x00" * 32)


def test_audio_cd_is_recognised_by_its_cda_tracks(tmp_path):
    (tmp_path / "Track01.cda").write_bytes(b"")
    (tmp_path / "Track02.cda").write_bytes(b"")
    assert classify_root(tmp_path) is DiscType.CD


def test_dvd_video_is_recognised_by_video_ts(tmp_path):
    (tmp_path / "VIDEO_TS").mkdir()
    assert classify_root(tmp_path) is DiscType.DVD


@pytest.mark.parametrize("version", [b"0100", b"0200"])
def test_blu_ray_is_recognised_by_bdmv(tmp_path, version):
    _bdmv(tmp_path, version)
    assert classify_root(tmp_path) is DiscType.BD


def test_uhd_blu_ray_is_recognised_by_index_bdmv_version_3(tmp_path):
    _bdmv(tmp_path, b"0300")
    assert classify_root(tmp_path) is DiscType.UHD


def test_bdmv_without_readable_index_counts_as_blu_ray(tmp_path):
    (tmp_path / "BDMV").mkdir()
    assert classify_root(tmp_path) is DiscType.BD


def test_data_disc_is_not_a_disc_type(tmp_path):
    (tmp_path / "setup.exe").write_bytes(b"MZ")
    (tmp_path / "docs").mkdir()
    assert classify_root(tmp_path) is None
