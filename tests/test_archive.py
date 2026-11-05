"""Filing to the Archive: Plex must never see a partially written file, and nothing
counts as filed (so scratch stays) until every file is verified in place."""

from __future__ import annotations

import shutil

import pytest

from ama.archive import PARTIAL, Archive, FilingError, safe_name
from ama.config import Library, LibraryKind
from ama.jobs import JobStatus
from tests.test_cd_archive import DISC_1, SPECIAL, _insert, _response, _wait_for
from tests.conftest import eventually


def _sources(tmp_path):
    src = tmp_path / "scratch"
    src.mkdir()
    (src / "01.flac").write_bytes(b"one" * 1000)
    (src / "02.flac").write_bytes(b"two" * 1000)
    return {"01 - A.flac": src / "01.flac", "02 - B.flac": src / "02.flac"}


def _libraries(root):
    return [Library(name=k.folder, kind=k, path=str(root / k.folder), default=True)
            for k in LibraryKind]


def test_files_are_written_under_a_temporary_name_then_renamed(tmp_path):
    seen = []

    def watching_copy(src, dest):
        # While a file is being written, no media file with a final name is half-done.
        seen.append(dest.name)
        assert dest.name.endswith(PARTIAL)
        shutil.copyfile(src, dest)

    archive = Archive(_libraries(tmp_path / "libraries"), copy=watching_copy)
    folder = archive.place(tmp_path.joinpath("Music", "X", "Y").relative_to(tmp_path),
                           _sources(tmp_path))
    assert sorted(p.name for p in folder.iterdir()) == ["01 - A.flac", "02 - B.flac"]
    assert seen == ["01 - A.flac" + PARTIAL, "02 - B.flac" + PARTIAL]


def test_a_copy_that_comes_out_different_is_not_renamed_into_place(tmp_path):
    def truncating_copy(src, dest):
        dest.write_bytes(src.read_bytes()[:10])

    archive = Archive(_libraries(tmp_path / "libraries"), copy=truncating_copy)
    with pytest.raises(FilingError):
        archive.place(tmp_path.joinpath("Music").relative_to(tmp_path), _sources(tmp_path))
    assert list((tmp_path / "libraries" / "Music").iterdir()) == []


def test_filing_again_skips_files_already_in_place(tmp_path):
    copies = []
    archive = Archive(_libraries(tmp_path / "libraries"), copy=lambda s, d: (copies.append(d), shutil.copyfile(s, d)))
    files = _sources(tmp_path)
    archive.place(tmp_path.joinpath("Music").relative_to(tmp_path), files)
    archive.place(tmp_path.joinpath("Music").relative_to(tmp_path), files)
    assert len(copies) == 2


def test_names_are_made_safe_for_windows():
    assert safe_name('AC/DC: "Live" at <Donington>?') == "AC_DC_ _Live_ at _Donington__"
    assert safe_name("Hello...  ") == "Hello"
    assert safe_name("CON") == "CON_"
    assert len(safe_name("x" * 300)) == 80


def test_a_disc_whose_filing_cant_be_verified_keeps_its_scratch(harness, client):
    harness.services.archive.copy = lambda src, dest: dest.write_bytes(b"garbage")
    _insert(harness, DISC_1, 24, _response(only=SPECIAL))
    rec = _wait_for(harness, JobStatus.RIPPED)
    eventually(lambda: any("Couldn't file to" in ln.text
                           for ln in harness.services.jobs.log_lines(rec.id)))
    assert harness.services.jobs.get(rec.id).status == JobStatus.RIPPED
    assert len(list(rec.scratch_dir.glob("*.flac"))) == 24
    harness.services.archive.copy = shutil.copyfile  # e.g. the Library folder came back
    _wait_for(harness, JobStatus.FILED)
