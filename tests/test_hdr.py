"""HDR10 static metadata (ADR-0003): read from ffprobe, compared source vs Encode.

Fixtures are real ffprobe 9.0.2 captures (tests/data/README.md): a libx265 HDR10
clip, and the same clip after AMA's hevc_nvenc Encode on the archive PC.
"""

from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

from ama.hdr import colour_args, differences, parse_hdr

DATA = Path(__file__).parent / "data" / "ffprobe"
SOURCE = (DATA / "hdr10-source.json").read_text(encoding="utf-8")
ENCODE = (DATA / "hdr10-encode.json").read_text(encoding="utf-8")


def _edited(text: str, edit) -> str:
    data = json.loads(text)
    edit(data["frames"][0], data["streams"][0])
    return json.dumps(data)


def _drop_side_data(kind: str):
    def edit(frame, stream):
        for holder in (frame, stream):
            holder["side_data_list"] = [d for d in holder.get("side_data_list", [])
                                        if d["side_data_type"] != kind]
    return edit


def test_an_hdr10_source_is_read_with_its_colour_tags_mastering_display_and_light_levels():
    info = parse_hdr(SOURCE)
    assert info.is_hdr10
    assert (info.colour.primaries, info.colour.transfer, info.colour.space,
            info.colour.range) == ("bt2020", "smpte2084", "bt2020nc", "tv")
    md = info.mastering
    assert md is not None
    assert md.red == (Fraction(34000, 50000), Fraction(16000, 50000))
    assert md.white == (Fraction(15635, 50000), Fraction(16450, 50000))
    assert (md.min_luminance, md.max_luminance) == (Fraction(50, 10000), Fraction(1000))
    assert (info.max_cll, info.max_fall) == (1000, 400)
    assert not info.dolby_vision and not info.hdr10_plus


def test_the_real_nvenc_encode_matches_its_source():
    assert differences(parse_hdr(SOURCE), parse_hdr(ENCODE)) == []


def test_lost_or_changed_metadata_is_reported():
    lost = parse_hdr(_edited(ENCODE, _drop_side_data("Mastering display metadata")))
    assert differences(parse_hdr(SOURCE), lost) == ["the mastering display metadata is missing"]

    def changed(frame, stream):
        frame["color_transfer"] = stream["color_transfer"] = "bt709"
        for holder in (frame, stream):
            for d in holder.get("side_data_list", []):
                if d["side_data_type"] == "Content light level metadata":
                    d["max_content"] = 4000
    assert differences(parse_hdr(SOURCE), parse_hdr(_edited(ENCODE, changed))) == [
        "transfer is bt709, not smpte2084", "MaxCLL is 4000, not 1000"]


def test_dolby_vision_or_hdr10_plus_left_in_the_encode_is_reported():
    def dv(frame, stream):
        stream.setdefault("side_data_list", []).append(
            {"side_data_type": "DOVI configuration record", "dv_profile": 8})
        frame["side_data_list"].append(
            {"side_data_type": "HDR Dynamic Metadata SMPTE2094-40 (HDR10+)"})
    source = parse_hdr(_edited(SOURCE, dv))
    assert source.dolby_vision and source.hdr10_plus
    assert differences(source, parse_hdr(ENCODE)) == []  # dropped, as ADR-0003 says
    assert differences(parse_hdr(SOURCE), parse_hdr(_edited(ENCODE, dv))) == [
        "Dolby Vision metadata is still there", "HDR10+ metadata is still there"]


def test_sdr_video_is_not_hdr10_and_untagged_colour_gives_no_arguments():
    sdr = json.dumps({"frames": [{"color_primaries": "bt709", "color_transfer": "bt709"}],
                      "streams": [{"index": 0}]})
    assert not parse_hdr(sdr).is_hdr10
    assert parse_hdr(sdr).mastering is None
    blank = parse_hdr(json.dumps({"frames": [], "streams": [{"color_range": "unknown"}]}))
    assert colour_args(blank.colour) == []


def test_colour_tags_become_ffmpeg_arguments():
    assert colour_args(parse_hdr(SOURCE).colour) == [
        "-color_primaries", "bt2020", "-color_trc", "smpte2084", "-colorspace", "bt2020nc",
        "-color_range", "tv"]
