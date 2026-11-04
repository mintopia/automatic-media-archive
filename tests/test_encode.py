"""The Encode's pure parts: which streams of the Main Feature are kept, the ffmpeg
command, and reading ffmpeg's progress. Stream lists are shaped like ffprobe's
JSON for MakeMKV output (language tags ISO 639-2, MakeMKV track titles)."""

from __future__ import annotations

import json
from pathlib import Path

from ama.encode import ProgressReader, ffmpeg_args, parse_probe, select_streams
from ama.drive import DiscType


def _s(index, kind, codec, lang="", title="", **disp) -> dict:
    return {"index": index, "codec_type": kind, "codec_name": codec,
            "tags": {k: v for k, v in (("language", lang), ("title", title)) if v},
            "disposition": {"default": 0, "forced": 0, "comment": 0, "hearing_impaired": 0,
                            "attached_pic": 0, **disp}}


def _probe(*streams, duration="7293.5") -> str:
    return json.dumps({"streams": list(streams), "chapters": [{"id": 0}],
                       "format": {"duration": duration}})


ENGLISH_FILM = _probe(
    _s(0, "video", "h264"),
    _s(1, "audio", "truehd", "eng", "Surround 7.1", default=1),
    _s(2, "audio", "ac3", "eng", "Stereo"),
    _s(3, "audio", "ac3", "fra", "Surround 5.1"),
    _s(4, "audio", "ac3", "eng", "Director's Commentary"),
    _s(5, "subtitle", "hdmv_pgs_subtitle", "eng"),
    _s(6, "subtitle", "hdmv_pgs_subtitle", "eng", "Forced", forced=1),
    _s(7, "subtitle", "hdmv_pgs_subtitle", "fra"),
    _s(8, "subtitle", "hdmv_pgs_subtitle", "spa", forced=1),
)

JAPANESE_FILM = _probe(
    _s(0, "video", "h264"),
    _s(1, "audio", "dts", "eng", "Surround 5.1", default=1),
    _s(2, "audio", "truehd", "jpn", "Surround 5.1"),
    _s(3, "audio", "ac3", "jpn", "Stereo"),
    _s(4, "audio", "ac3", "eng", "Commentary", comment=1),
    _s(5, "audio", "ac3", "fra", "Surround 5.1"),
    _s(6, "subtitle", "hdmv_pgs_subtitle", "eng", "SDH", hearing_impaired=1),
    _s(7, "subtitle", "hdmv_pgs_subtitle", "eng"),
    _s(8, "subtitle", "hdmv_pgs_subtitle", "jpn"),
)


def _kept(sel) -> list[int]:
    return [s.index for s in sel.streams]


def test_an_english_film_keeps_every_english_audio_track_and_english_plus_forced_subtitles():
    sel = select_streams(parse_probe(ENGLISH_FILM), original_language="en")
    assert _kept(sel) == [0, 1, 2, 4, 5, 6]
    assert sel.default_audio.index == 1
    assert sel.forced_subtitle.index == 6
    assert sel.default_subtitle is None  # an English film shows only the forced subtitles


def test_a_non_english_film_also_keeps_its_original_language_track():
    sel = select_streams(parse_probe(JAPANESE_FILM), original_language="ja")
    # English (incl. commentary) + the main Japanese track; the Japanese stereo and French go.
    assert _kept(sel) == [0, 1, 2, 4, 6, 7]
    assert sel.default_audio.index == 2  # the film in its own language
    assert sel.default_subtitle.index == 7  # full English subtitles, not SDH


def test_original_language_codes_match_both_iso_639_2_forms():
    probe = parse_probe(_probe(_s(0, "video", "mpeg2video"),
                               _s(1, "audio", "ac3", "ger"), _s(2, "audio", "ac3", "eng")))
    assert _kept(select_streams(probe, original_language="de")) == [0, 1, 2]
    probe = parse_probe(_probe(_s(0, "video", "mpeg2video"),
                               _s(1, "audio", "ac3", "deu"), _s(2, "audio", "ac3", "eng")))
    assert _kept(select_streams(probe, original_language="de")) == [0, 1, 2]


def test_a_film_with_no_english_or_original_audio_still_keeps_its_first_audio_track():
    probe = parse_probe(_probe(_s(0, "video", "mpeg2video"), _s(1, "audio", "ac3", "ita"),
                               _s(2, "audio", "ac3", "spa")))
    sel = select_streams(probe, original_language="fr")
    assert _kept(sel) == [0, 1]
    assert sel.default_audio.index == 1


def test_untagged_forced_subtitles_are_kept_and_cover_art_is_not_the_video():
    probe = parse_probe(_probe(_s(0, "video", "mjpeg", attached_pic=1), _s(1, "video", "h264"),
                               _s(2, "audio", "ac3", "eng"),
                               _s(3, "subtitle", "dvd_subtitle", "", "Forced Subtitles")))
    sel = select_streams(probe, original_language="en")
    assert _kept(sel) == [1, 2, 3]
    assert sel.forced_subtitle.index == 3


def test_probe_reads_duration_and_video_height_and_tolerates_stderr_noise():
    text = "[matroska @ 0x1] some warning\n" + json.dumps(
        {"streams": [_s(0, "video", "h264") | {"height": 1080}], "format": {"duration": "60.5"}})
    probe = parse_probe(text)
    assert probe.duration_s == 60.5
    assert probe.height == 1080


def test_the_ffmpeg_command_encodes_hevc_nvenc_10_bit_at_the_disc_types_cq_and_copies_the_rest():
    sel = select_streams(parse_probe(JAPANESE_FILM), original_language="ja")
    args = ffmpeg_args(Path("ffmpeg.exe"), Path("in.mkv"), Path("out.tmp.mkv"), sel, cq=22,
                       title="Spirited Away (2001)")
    line = " ".join(args)
    assert args[0] == "ffmpeg.exe" and args[-1] == "out.tmp.mkv"
    assert "-c:v hevc_nvenc" in line and "-profile:v main10" in line
    assert "-pix_fmt p010le" in line and "-cq 22" in line
    assert "-c:a copy" in line and "-c:s copy" in line  # audio/subtitles passed through untouched
    assert "-map_chapters 0" in line
    assert "-progress pipe:1" in line
    maps = [args[i + 1] for i, a in enumerate(args) if a == "-map"]
    assert maps == ["0:0", "0:1", "0:2", "0:4", "0:6", "0:7"]
    disp = {a: args[i + 1] for i, a in enumerate(args) if a.startswith("-disposition")}
    assert disp == {"-disposition:a:0": "0", "-disposition:a:1": "default+original",
                    "-disposition:a:2": "comment", "-disposition:s:0": "hearing_impaired",
                    "-disposition:s:1": "default"}
    assert "title=Spirited Away (2001)" in args


def test_an_english_films_forced_subtitles_are_flagged_default_and_forced():
    sel = select_streams(parse_probe(ENGLISH_FILM), original_language="en")
    args = ffmpeg_args(Path("ffmpeg"), Path("in.mkv"), Path("out.mkv"), sel, cq=20, title="X")
    disp = {a: args[i + 1] for i, a in enumerate(args) if a.startswith("-disposition")}
    assert disp["-disposition:s:0"] == "0"
    assert disp["-disposition:s:1"] == "default+forced"
    assert disp["-disposition:a:0"] == "default+original"


def test_progress_reader_turns_ffmpeg_progress_blocks_into_fraction_and_speed():
    r = ProgressReader(duration_s=100.0)
    lines = ["frame=10", "fps=0.0", "out_time_us=N/A", "speed=N/A", "progress=continue",
             "frame=500", "out_time_us=25000000", "out_time_ms=25000000", "speed= 2.5x",
             "progress=continue"]
    updates = [u for u in map(r.feed, lines) if u is not None]
    assert [(u.fraction, u.speed) for u in updates] == [(0.0, None), (0.25, 2.5)]
    assert updates[-1].eta_s == 30  # 75 s of film left at 2.5x
    assert r.feed("[hevc_nvenc @ 0x1] a warning") is None
    assert r.feed("progress=end").fraction == 1.0


def test_cq_comes_from_the_disc_type():
    from ama.config import CqConfig
    from ama.encode import cq_for
    cq = CqConfig(dvd=19, bd=22, uhd=24)
    assert [cq_for(cq, t) for t in (DiscType.DVD, DiscType.BD, DiscType.UHD)] == [19, 22, 24]
