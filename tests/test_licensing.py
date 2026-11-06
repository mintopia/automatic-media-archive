"""AMA is MIT, with every third-party licence accounted for (ADR 0012)."""

from __future__ import annotations

import importlib.metadata
import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "src" / "ama" / "web" / "static"
NOTICES = ROOT / "THIRD_PARTY_NOTICES.md"


def _runtime_packages() -> set[str]:
    """Every package uv.lock installs for AMA at runtime, direct and transitive, on any platform."""
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    deps = {p["name"]: [d["name"] for d in p.get("dependencies", [])] for p in lock["package"]}
    seen: set[str] = set()
    todo = list(deps["ama"])
    while todo:
        name = todo.pop()
        if name not in seen:
            seen.add(name)
            todo.extend(deps[name])
    return seen


def test_ama_is_mit_licensed():
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert text.startswith("MIT License")
    assert "Copyright (c) 2026 Jessica Smith" in text
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["license"] == "MIT"


@pytest.mark.parametrize("package", sorted(_runtime_packages()))
def test_every_runtime_dependency_is_in_the_notices(package):
    rows = NOTICES.read_text(encoding="utf-8")
    assert re.search(rf"^\| {re.escape(package)} \|", rows, re.MULTILINE | re.IGNORECASE)


@pytest.mark.parametrize("tool", ["ffmpeg", "cyanrip", "MakeMKV", "htmx", "htmx SSE extension", "Archivo"])
def test_every_external_tool_and_vendored_file_is_in_the_notices(tool):
    rows = NOTICES.read_text(encoding="utf-8")
    assert re.search(rf"^\| {re.escape(tool)} \|", rows, re.MULTILINE)


def test_no_gpl_dependency_remains():
    for package in _runtime_packages():
        meta = importlib.metadata.metadata(package)
        licence = " ".join(
            [meta.get("License-Expression") or "", meta.get("License") or "", *(meta.get_all("Classifier") or [])]
        )
        assert not re.search(r"(?<!L)GPL|(?<!Lesser )General Public License", licence), package


@pytest.mark.parametrize(
    "licence", [STATIC / "vendor" / "LICENSE-htmx.txt", STATIC / "fonts" / "OFL-Archivo.txt"]
)
def test_vendored_licence_texts_ship_next_to_the_files(licence):
    assert licence.read_text(encoding="utf-8").strip()
