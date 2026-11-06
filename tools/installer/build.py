"""Build the Windows installer, AMA-Setup-X.Y.Z.exe (ADR 0017).

    uv run python tools/installer/build.py [--out DIR] [--iscc PATH] [--stage-only]

The installer carries uv.exe (pinned, hash-checked), AMA's wheel and its locked
requirements, and nothing else redistributable: at install time uv installs the
pinned Python and the requirements from PyPI (ADR 0012). Needs Inno Setup 6 (ISCC.exe:
--iscc, $ISCC, PATH or its usual install folders) and network access for the uv download.
Runs unattended; exits non-zero on any failure. The installer is unsigned for now.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import shutil
import subprocess
import sys
import tomllib
import urllib.request
import zipfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent

UV_VERSION = "0.13.7"
UV_ZIP = "uv-x86_64-pc-windows-msvc.zip"
UV_SHA256 = "0cdc5b38fe5a8168ed6a25814f5ba43c21d313dd3187314fccb37b7cec46e021"
UV_URL = f"https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/{UV_ZIP}"
# The Python the installer installs; inside pyproject.toml's requires-python.
PYTHON_VERSION = "3.13.18"


class BuildError(Exception):
    pass


def project_version(pyproject: Path) -> str:
    return tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]


def _download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read()


def fetch_uv(cache: Path, stage: Path, download: Callable[[str], bytes] = _download,
             sha256: str = UV_SHA256) -> None:
    """Put the pinned uv.exe in `stage`, downloading the release zip into `cache` once.
    A download whose hash isn't `sha256` is refused and not kept."""
    cached = cache / f"uv-{UV_VERSION}-{UV_ZIP}"
    if cached.exists() and hashlib.sha256(cached.read_bytes()).hexdigest() == sha256:
        archive = cached.read_bytes()
    else:
        archive = download(UV_URL)
        actual = hashlib.sha256(archive).hexdigest()
        if actual != sha256:
            raise BuildError(f"{UV_URL}: sha256 is {actual}, expected {sha256}")
        cache.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(archive)
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        (stage / "uv.exe").write_bytes(z.read("uv.exe"))


def _usual_isccs(env: Mapping[str, str]) -> list[Path]:
    roots = [env.get("LOCALAPPDATA", "") and Path(env["LOCALAPPDATA"]) / "Programs",
             env.get("ProgramFiles(x86)", "") and Path(env["ProgramFiles(x86)"]),
             env.get("ProgramFiles", "") and Path(env["ProgramFiles"])]
    return [root / "Inno Setup 6" / "ISCC.exe" for root in roots if root]


def find_iscc(env: Mapping[str, str], usual: Sequence[Path]) -> Path:
    """ISCC.exe: $ISCC, then PATH, then the usual install folders."""
    if env.get("ISCC"):
        return Path(env["ISCC"])
    on_path = shutil.which("ISCC", path=env.get("PATH"))
    if on_path:
        return Path(on_path)
    for candidate in usual:
        if candidate.is_file():
            return candidate
    raise BuildError("Inno Setup 6 isn't installed (no ISCC.exe). Install it from "
                     "https://jrsoftware.org/isinfo.php (per-user: run its installer with "
                     "/CURRENTUSER), or pass --iscc or set ISCC.")


def _run(command: list[str | Path]) -> None:
    print("+", " ".join(str(c) for c in command), flush=True)
    subprocess.run([str(c) for c in command], cwd=ROOT, check=True)


def stage(stage_dir: Path, cache: Path) -> str:
    """Fill `stage_dir` with what the installer carries; return the wheel's file name."""
    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    (stage_dir / "licenses").mkdir(parents=True)
    _run(["uv", "build", "--wheel", "--out-dir", stage_dir])
    [wheel] = stage_dir.glob("ama-*.whl")
    _run(["uv", "export", "--quiet", "--frozen", "--no-dev", "--no-emit-project",
          "--format", "requirements.txt", "--output-file", stage_dir / "requirements.txt"])
    fetch_uv(cache, stage_dir)
    shutil.copy2(HERE / "install-env.cmd", stage_dir)
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(ROOT / name, stage_dir)
    for licence in (HERE / "licenses").iterdir():
        shutil.copy2(licence, stage_dir / "licenses")
    return wheel.name


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build AMA-Setup-X.Y.Z.exe")
    parser.add_argument("--out", type=Path, default=ROOT / "dist",
                        help="where the installer goes (default: dist)")
    parser.add_argument("--iscc", type=Path, help="Inno Setup's ISCC.exe")
    parser.add_argument("--stage-only", action="store_true",
                        help="stop after staging the files (no Inno Setup needed)")
    args = parser.parse_args(argv)
    work = ROOT / "build" / "installer"
    version = project_version(ROOT / "pyproject.toml")
    try:
        iscc = None if args.stage_only else (
            args.iscc or find_iscc(os.environ, _usual_isccs(os.environ)))
        wheel = stage(work / "stage", work / "cache")
        if iscc is None:
            print(f"staged {work / 'stage'}")
            return 0
        args.out.mkdir(parents=True, exist_ok=True)
        _run([iscc, "/Q",
              f"/DAppVersion={version}", f"/DPythonVersion={PYTHON_VERSION}",
              f"/DWheel={wheel}", f"/DStageDir={work / 'stage'}",
              f"/DOutputDir={args.out.resolve()}", HERE / "ama.iss"])
    except (BuildError, subprocess.CalledProcessError, OSError) as e:
        print(f"build.py: {e}", file=sys.stderr)
        return 1
    print(args.out.resolve() / f"AMA-Setup-{version}.exe")
    return 0


if __name__ == "__main__":
    sys.exit(main())
