"""The Windows installer's build script and Inno Setup script (#75, ADR 0017)."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import re
import tomllib
import zipfile
from pathlib import Path

import pytest

from ama import start_at_login

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "tools" / "installer"
_spec = importlib.util.spec_from_file_location("installer_build", INSTALLER / "build.py")
build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build)


def _uv_zip() -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("uv.exe", b"MZ uv")
        z.writestr("uvx.exe", b"MZ uvx")
    return out.getvalue()


def test_the_pinned_python_is_an_exact_version_ama_supports():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["requires-python"] == ">=3.13,<3.14"  # update the pin with it
    assert re.fullmatch(r"3\.13\.\d+", build.PYTHON_VERSION)


def test_the_installer_version_is_the_pyproject_version(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "ama"\nversion = "1.4.2"\n',
                                             encoding="utf-8")
    assert build.project_version(tmp_path / "pyproject.toml") == "1.4.2"


def test_uv_is_taken_from_the_download_when_its_hash_matches(tmp_path):
    archive = _uv_zip()
    downloads: list[str] = []

    def download(url: str) -> bytes:
        downloads.append(url)
        return archive

    stage = tmp_path / "stage"
    stage.mkdir()
    for _ in range(2):  # the second build reuses the cached download
        build.fetch_uv(tmp_path / "cache", stage, download=download,
                       sha256=hashlib.sha256(archive).hexdigest())
    assert (stage / "uv.exe").read_bytes() == b"MZ uv"
    assert not (stage / "uvx.exe").exists()
    assert len(downloads) == 1 and build.UV_VERSION in downloads[0]


def test_a_uv_download_with_the_wrong_hash_is_refused(tmp_path):
    stage = tmp_path / "stage"
    stage.mkdir()
    with pytest.raises(build.BuildError, match="sha256"):
        build.fetch_uv(tmp_path / "cache", stage, download=lambda url: _uv_zip(),
                       sha256="0" * 64)
    assert not (stage / "uv.exe").exists()
    assert not any((tmp_path / "cache").glob("*.zip"))


def test_iscc_is_found_from_the_environment_first(tmp_path):
    named = tmp_path / "named" / "ISCC.exe"
    usual = tmp_path / "usual" / "ISCC.exe"
    for exe in (named, usual):
        exe.parent.mkdir()
        exe.write_bytes(b"MZ")
    assert build.find_iscc({"ISCC": str(named)}, [usual]) == named
    assert build.find_iscc({}, [tmp_path / "missing" / "ISCC.exe", usual]) == usual


def test_without_inno_setup_the_build_says_how_to_get_it(tmp_path):
    with pytest.raises(build.BuildError, match="Inno Setup"):
        build.find_iscc({"PATH": str(tmp_path)}, [tmp_path / "missing" / "ISCC.exe"])


def test_the_installer_registers_start_at_login_as_the_tray_does(tmp_path):
    """The tray's "Start at login" shows ticked only when the Run value is exactly its own."""
    script = (INSTALLER / "ama.iss").read_text(encoding="utf-8")
    assert f'#define RunValueName "{start_at_login.NAME}"' in script
    assert f"RunKey = '{start_at_login.RUN_KEY}';" in script

    app, config = tmp_path / "Programs" / "AMA", tmp_path / "AMA" / "ama.toml"
    scripts = app / "venv" / "Scripts"
    scripts.mkdir(parents=True)
    for exe in ("python.exe", "pythonw.exe"):
        (scripts / exe).write_bytes(b"MZ")
    [expression] = re.findall(r"function RunCommand\(\): String;\s*begin\s*Result := (.+?);", script)
    values = {"AppDir": str(app), "ConfigPath('')": str(config)}
    rendered = "".join(token[1:-1] if token.startswith("'") else values[token]
                       for token in expression.split(" + "))
    assert rendered == start_at_login.command_line(scripts / "python.exe", config)
