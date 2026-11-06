"""The release workflow's guard: a `vX.Y.Z` tag must match the pyproject.toml version."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "release" / "check_tag_version.py"
_spec = importlib.util.spec_from_file_location("check_tag_version", SCRIPT)
check_tag_version = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_tag_version)


def _pyproject(tmp_path, version):
    path = tmp_path / "pyproject.toml"
    path.write_text(f'[project]\nname = "ama"\nversion = "{version}"\n', encoding="utf-8")
    return path


def test_a_tag_matching_the_version_passes(tmp_path, capsys):
    assert check_tag_version.main(["v1.2.3", str(_pyproject(tmp_path, "1.2.3"))]) == 0
    assert "1.2.3" in capsys.readouterr().out


def test_a_tag_that_does_not_match_the_version_fails(tmp_path, capsys):
    assert check_tag_version.main(["v1.2.4", str(_pyproject(tmp_path, "1.2.3"))]) == 1
    err = capsys.readouterr().err
    assert "v1.2.4" in err and "1.2.3" in err


@pytest.mark.parametrize(
    ("tag", "version"),
    [
        ("v1.2.3-rc1", "1.2.3-rc1"),  # matched by the workflow's v*.*.* glob, but not vX.Y.Z
        ("v1.02.3", "1.02.3"),
        ("cyanrip-0.9.4", "cyanrip-0.9.4"),  # cyanrip builds are never AMA releases
    ],
)
def test_a_tag_that_is_not_plain_vX_Y_Z_fails_even_if_it_matches(tmp_path, capsys, tag, version):
    assert check_tag_version.main([tag, str(_pyproject(tmp_path, version))]) == 1
    assert "vX.Y.Z" in capsys.readouterr().err
