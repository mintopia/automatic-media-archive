"""AMA's own FLAC tag writer (ADR 0012).

It replaces a FLAC's VORBIS_COMMENT block, puts the slack in a PADDING block, and
never touches the audio frames. When the new tags fit in the space the old tags and
padding took, only the metadata is rewritten in place; otherwise the file is
rewritten (to a temporary file, then swapped in) with fresh padding. Writing the same
tags again gives the same file.
"""

from __future__ import annotations

import os
from pathlib import Path

_MAGIC = b"fLaC"
_STREAMINFO, _PADDING, _VORBIS_COMMENT = 0, 1, 4
_LAST = 0x80
_MAX_BLOCK = (1 << 24) - 1
_NEW_PADDING = 8192  # what ffmpeg's FLAC muxer (and so cyanrip) leaves
_VENDOR = b"AMA"

Tags = dict[str, list[str]]


class _Flac:
    """A FLAC's metadata blocks [(type, body)] and where its audio frames start."""

    def __init__(self, path: Path) -> None:
        with path.open("rb") as f:
            if f.read(4) != _MAGIC:
                raise ValueError(f"{path} is not a FLAC file")
            self.blocks: list[tuple[int, bytes]] = []
            while True:
                header = f.read(4)
                if len(header) < 4:
                    raise ValueError(f"{path}: metadata ends early")
                body = f.read(int.from_bytes(header[1:], "big"))
                self.blocks.append((header[0] & 0x7F, body))
                if header[0] & _LAST:
                    break
            self.audio_start = f.tell()
        if not self.blocks or self.blocks[0][0] != _STREAMINFO:
            raise ValueError(f"{path}: no STREAMINFO block")


def read_tags(path: Path) -> Tags:
    """The FLAC's Vorbis comments, keys upper-cased, values in file order."""
    tags: Tags = {}
    for kind, body in _Flac(path).blocks:
        if kind == _VORBIS_COMMENT:
            for comment in _parse_comments(body)[1]:
                key, _, value = comment.partition("=")
                tags.setdefault(key.upper(), []).append(value)
    return tags


def write_tags(path: Path, tags: Tags) -> None:
    """Replace every tag in the FLAC at `path` with `tags` (idempotent)."""
    flac = _Flac(path)
    vendor = next((_parse_comments(body)[0] for kind, body in flac.blocks
                   if kind == _VORBIS_COMMENT), _VENDOR)
    comment = _comment_block(vendor, tags)
    if len(comment) > _MAX_BLOCK:
        raise ValueError(f"{path}: tags too big for a FLAC block")

    # The tags go where the old ones were, else straight after STREAMINFO.
    kept: list[tuple[int, bytes]] = []
    for kind, body in flac.blocks:
        if kind == _VORBIS_COMMENT and not any(k == _VORBIS_COMMENT for k, _ in kept):
            kept.append((_VORBIS_COMMENT, comment))
        elif kind not in (_VORBIS_COMMENT, _PADDING):
            kept.append((kind, body))
    if not any(k == _VORBIS_COMMENT for k, _ in kept):
        kept.insert(1, (_VORBIS_COMMENT, comment))

    room = flac.audio_start - len(_MAGIC)
    used = sum(4 + len(body) for _, body in kept)
    if used == room:
        _write_in_place(path, _metadata(kept))
    elif used + 4 <= room:
        _write_in_place(path, _metadata(kept + [(_PADDING, bytes(room - used - 4))]))
    else:
        _rewrite(path, _metadata(kept + [(_PADDING, bytes(_NEW_PADDING))]), flac.audio_start)


def _parse_comments(body: bytes) -> tuple[bytes, list[str]]:
    def u32(i: int) -> int:
        return int.from_bytes(body[i:i + 4], "little")

    n = u32(0)
    vendor, i = body[4:4 + n], 4 + n
    count, i = u32(i), i + 4
    comments = []
    for _ in range(count):
        n = u32(i)
        comments.append(body[i + 4:i + 4 + n].decode("utf-8", errors="replace"))
        i += 4 + n
    return vendor, comments


def _comment_block(vendor: bytes, tags: Tags) -> bytes:
    comments = [f"{k}={v}".encode() for k, values in tags.items() for v in values]
    out = [len(vendor).to_bytes(4, "little"), vendor, len(comments).to_bytes(4, "little")]
    for c in comments:
        out += [len(c).to_bytes(4, "little"), c]
    return b"".join(out)


def _metadata(blocks: list[tuple[int, bytes]]) -> bytes:
    out = [_MAGIC]
    for i, (kind, body) in enumerate(blocks):
        last = _LAST if i == len(blocks) - 1 else 0
        out += [bytes([kind | last]), len(body).to_bytes(3, "big"), body]
    return b"".join(out)


def _write_in_place(path: Path, metadata: bytes) -> None:
    with path.open("r+b") as f:
        f.write(metadata)


def _rewrite(path: Path, metadata: bytes, audio_start: int) -> None:
    tmp = path.with_name(path.name + ".tagging")
    with path.open("rb") as src, tmp.open("wb") as dst:
        dst.write(metadata)
        src.seek(audio_start)
        while chunk := src.read(1 << 20):
            dst.write(chunk)
    os.replace(tmp, path)
