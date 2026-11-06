"""AMA's own FLAC tag writer (ADR 0012): it replaces the VORBIS_COMMENT block,
reuses PADDING, and never touches the audio frames.

The fixture is a FLAC from AMA's pinned ffmpeg, whose libavformat FLAC muxer is the
one cyanrip writes its rips with (tests/data/README.md).
"""

from __future__ import annotations

import shutil

import pytest

from ama.flactags import read_tags, write_tags
from tests.fakes import DATA, flac_bytes

FIXTURE = DATA / "flac" / "ffmpeg-tagged-sine.flac"

TAGS = {
    "TITLE": ["The Unknown Journey Continues"],
    "ARTIST": ["島翔太朗 & 西木康智"],
    "ALBUM": ["FINAL FANTASY VII REBIRTH Original Soundtrack"],
    "TRACKNUMBER": ["1"],
    "LABEL": ["Square Enix Music", "SQEX"],
    "MUSICBRAINZ_DISCID": ["kIBdaUqY_5kMBgOXehaFmL5TSbA-"],
}


def _blocks(data: bytes) -> tuple[list[tuple[int, int]], int]:
    """[(block type, length)] of a FLAC's metadata, and where its audio frames start."""
    assert data[:4] == b"fLaC"
    blocks, i = [], 4
    while True:
        header = data[i]
        length = int.from_bytes(data[i + 1:i + 4], "big")
        blocks.append((header & 0x7F, length))
        i += 4 + length
        if header & 0x80:
            return blocks, i


def _audio(data: bytes) -> bytes:
    return data[_blocks(data)[1]:]


@pytest.fixture
def flac(tmp_path):
    path = tmp_path / "01.flac"
    shutil.copy(FIXTURE, path)
    return path


def test_tags_are_replaced_and_the_audio_frames_are_untouched(flac):
    before = flac.read_bytes()
    assert read_tags(flac)["TITLE"] == ["Track 01"]   # what the muxer wrote

    write_tags(flac, TAGS)

    after = flac.read_bytes()
    assert read_tags(flac) == TAGS                     # old tags gone, multi-value kept
    assert _audio(after) == _audio(before)
    assert len(after) == len(before)                   # fitted in the existing padding
    assert [t for t, _ in _blocks(after)[0]] == [0, 4, 1]  # STREAMINFO, tags, padding


def test_tagging_twice_gives_the_same_file(flac):
    write_tags(flac, TAGS)
    once = flac.read_bytes()
    write_tags(flac, TAGS)
    assert flac.read_bytes() == once


def test_tags_too_big_for_the_padding_grow_the_file(flac):
    before = flac.read_bytes()
    big = {"COMMENT": ["x" * 20_000], "TITLE": ["Long"]}

    write_tags(flac, big)

    after = flac.read_bytes()
    assert read_tags(flac) == big
    assert _audio(after) == _audio(before)
    assert len(after) > len(before)
    write_tags(flac, big)
    assert flac.read_bytes() == after


def test_shrinking_back_reuses_the_grown_padding(flac):
    write_tags(flac, {"COMMENT": ["x" * 20_000]})
    grown = flac.read_bytes()
    write_tags(flac, TAGS)
    assert len(flac.read_bytes()) == len(grown)
    assert read_tags(flac) == TAGS


def test_a_file_without_tags_or_padding_gets_them(tmp_path):
    path = tmp_path / "01.flac"
    bare = flac_bytes(1, 2.0)                          # STREAMINFO only
    path.write_bytes(bare)
    assert read_tags(path) == {}

    write_tags(path, TAGS)

    assert read_tags(path) == TAGS
    assert path.read_bytes()[:4 + 4 + 34] == bare[:4] + bytes([0, 0, 0, 34]) + bare[8:]
    write_tags(path, {})
    assert read_tags(path) == {}


def test_a_file_that_is_not_flac_is_refused(tmp_path):
    path = tmp_path / "01.flac"
    path.write_bytes(b"RIFF....WAVE")
    with pytest.raises(ValueError):
        write_tags(path, TAGS)
    assert path.read_bytes() == b"RIFF....WAVE"
