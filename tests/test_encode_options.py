"""Each configurable Encode option (ADR 0010) changes the ffmpeg command as intended,
and the defaults give exactly the v1 NVENC HEVC command."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import pytest

from ama.encode import TrackPolicy, ffmpeg_args, parse_probe, select_streams
from ama.hdr import Colour, HdrInfo, MasteringDisplay
from tests.test_encode import ENGLISH_FILM, JAPANESE_FILM, _kept, _probe, _s

HDR10 = HdrInfo(Colour("bt2020", "smpte2084", "bt2020nc", "tv"),
                MasteringDisplay((Fraction(34000, 50000), Fraction(16000, 50000)),
                                 (Fraction(13250, 50000), Fraction(34500, 50000)),
                                 (Fraction(7500, 50000), Fraction(3000, 50000)),
                                 (Fraction(15635, 50000), Fraction(16450, 50000)),
                                 Fraction(50, 10000), Fraction(1000)),
                max_cll=1000, max_fall=400)


def _args(sel=None, **kw) -> list[str]:
    sel = sel or select_streams(parse_probe(ENGLISH_FILM), original_language="en")
    return ffmpeg_args(Path("ffmpeg"), Path("in.mkv"), Path("out.mkv"), sel, cq=22,
                       title="X", **kw)


def _opt(args: list[str], name: str) -> str | None:
    return args[args.index(name) + 1] if name in args else None


def test_the_defaults_give_the_v1_nvenc_hevc_command_exactly():
    sel = select_streams(parse_probe(JAPANESE_FILM), original_language="ja")
    args = ffmpeg_args(Path("ffmpeg.exe"), Path("in.mkv"), Path("out.tmp.mkv"), sel, cq=22,
                       title="Spirited Away (2001)", hdr=HDR10,
                       video_filter="crop=1920:800:0:140")
    assert args == [  # captured from v1 (feature/v2 cf639dd) before #28
        'ffmpeg.exe', '-hide_banner', '-nostdin', '-nostats', '-loglevel', 'warning',
        '-progress', 'pipe:1', '-y', '-hwaccel', 'cuda', '-i', 'in.mkv', '-map', '0:0',
        '-map', '0:1', '-map', '0:2', '-map', '0:4', '-map', '0:6', '-map', '0:7', '-vf',
        'crop=1920:800:0:140', '-map_chapters', '0', '-map_metadata', '0', '-metadata',
        'title=Spirited Away (2001)', '-c:v', 'hevc_nvenc', '-preset', 'p7', '-tune', 'hq',
        '-rc', 'vbr', '-cq', '22', '-b:v', '0', '-profile:v', 'main10', '-pix_fmt', 'p010le',
        '-rc-lookahead', '32', '-spatial-aq', '1', '-bf', '4', '-temporal-aq', '1',
        '-b_ref_mode', 'middle', '-color_primaries', 'bt2020', '-color_trc', 'smpte2084',
        '-colorspace', 'bt2020nc', '-color_range', 'tv', '-c:a', 'copy', '-c:s', 'copy',
        '-disposition:a:0', '0', '-disposition:a:1', 'default+original',
        '-disposition:a:2', 'comment', '-disposition:s:0', 'hearing_impaired',
        '-disposition:s:1', 'default', '-max_muxing_queue_size', '4096',
        '-default_mode', 'passthrough', '-f', 'matroska', 'out.tmp.mkv']


@pytest.mark.parametrize(("encoder", "quality", "pix_fmt", "hwaccel"), [
    ("hevc_nvenc", "-cq", "p010le", "cuda"),
    ("av1_nvenc", "-cq", "p010le", "cuda"),
    ("hevc_qsv", "-global_quality", "p010le", None),
    ("libx265", "-crf", "yuv420p10le", None),
])
def test_each_encoder_writes_10_bit_video_at_the_disc_types_constant_quality(
        encoder, quality, pix_fmt, hwaccel):
    args = _args(encoder=encoder)
    assert _opt(args, "-c:v") == encoder
    assert _opt(args, quality) == "22"
    assert _opt(args, "-pix_fmt") == pix_fmt
    assert _opt(args, "-hwaccel") == hwaccel
    assert "-b:v" not in args or _opt(args, "-b:v") == "0"  # never a plain bitrate
    assert args[-3:] == ["-f", "matroska", "out.mkv"]  # MKV whatever the encoder


@pytest.mark.parametrize(("encoder", "presets"), [
    ("hevc_nvenc", ["p4", "p6", "p7", "p7"]),
    ("av1_nvenc", ["p4", "p6", "p7", "p7"]),
    ("hevc_qsv", ["faster", "medium", "slower", "veryslow"]),
    ("libx265", ["fast", "medium", "slow", "slower"]),
])
def test_the_four_speed_steps_map_to_each_encoders_own_presets(encoder, presets):
    got = [_opt(_args(encoder=encoder, speed=s), "-preset")
           for s in ("faster", "balanced", "slower", "slowest")]
    assert got == presets


def test_nvencs_slowest_step_adds_a_full_resolution_second_pass():
    assert "-multipass" not in _args(speed="slower")
    assert _opt(_args(speed="slowest"), "-multipass") == "fullres"
    assert _opt(_args(encoder="av1_nvenc", speed="slowest"), "-multipass") == "fullres"


@pytest.mark.parametrize("encoder", ["hevc_nvenc", "av1_nvenc", "hevc_qsv", "libx265"])
def test_every_encoder_tags_an_hdr10_encode_with_the_sources_colour(encoder):
    line = " ".join(_args(encoder=encoder, hdr=HDR10))
    assert ("-color_primaries bt2020 -color_trc smpte2084 -colorspace bt2020nc "
            "-color_range tv") in line
    assert "-color_trc" not in " ".join(_args(encoder=encoder))  # SDR: left alone


def test_libx265_writes_the_hdr10_mastering_display_and_light_levels_itself():
    params = _opt(_args(encoder="libx265", hdr=HDR10), "-x265-params")
    assert params is not None
    assert "hdr10=1" in params and "repeat-headers=1" in params
    assert ("master-display=G(13250,34500)B(7500,3000)R(34000,16000)WP(15635,16450)"
            "L(10000000,50)") in params
    assert "max-cll=1000,400" in params
    assert "master-display" not in (_opt(_args(encoder="libx265"), "-x265-params") or "")


def test_a_max_resolution_scales_down_after_the_crop_and_keep_leaves_the_size():
    assert "-vf" not in _args(max_resolution="keep")
    box = ("scale=w='min(iw,1920)':h='min(ih,1080)':force_original_aspect_ratio=decrease"
           ":force_divisible_by=2")
    assert _opt(_args(max_resolution="1080p"), "-vf") == box
    assert _opt(_args(max_resolution="1080p", video_filter="crop=3840:1600:0:280"),
                "-vf") == "crop=3840:1600:0:280," + box
    assert "w='min(iw,1280)':h='min(ih,720)'" in _opt(_args(max_resolution="720p"), "-vf")


# --- sound and subtitles ---------------------------------------------------------

def test_copy_all_sound_keeps_every_audio_track():
    sel = select_streams(parse_probe(JAPANESE_FILM), "ja", TrackPolicy(audio="all"))
    assert [s.index for s in sel.audio] == [1, 2, 3, 4, 5]
    assert sel.default_audio.index == 2  # still the film in its own language


def test_first_track_plus_stereo_keeps_the_first_track_and_adds_an_aac_stereo_copy():
    sel = select_streams(parse_probe(JAPANESE_FILM), "ja",
                         TrackPolicy(audio="first_plus_stereo"))
    assert [s.index for s in sel.audio] == [1]
    args = _args(sel)
    maps = [args[i + 1] for i, a in enumerate(args) if a == "-map"]
    assert maps[:3] == ["0:0", "0:1", "0:1"]  # video, the first track, its stereo copy
    line = " ".join(args)
    assert "-c:a copy -c:a:1 aac -ac:a:1 2 -b:a:1 192k" in line
    assert "-metadata:s:a:1 title=Stereo" in line
    assert _opt(args, "-disposition:a:0") == "default"
    assert _opt(args, "-disposition:a:1") == "0"
    assert _opt(args, "-disposition:s:0") is not None  # subtitles follow after both


def test_preferred_languages_choose_the_sound_and_the_full_subtitles():
    probe = parse_probe(JAPANESE_FILM)
    # A Japanese speaker: the Japanese tracks, Japanese subtitles, nothing else.
    sel = select_streams(probe, "ja", TrackPolicy(languages=("ja",)))
    assert [s.index for s in sel.audio] == [2, 3]
    assert [s.index for s in sel.subtitles] == [8]
    assert sel.default_subtitle is None  # the film is in a language they speak
    # English first, then Japanese: an English viewer of a Japanese film.
    sel = select_streams(probe, "ja", TrackPolicy(languages=("en", "ja")))
    assert [s.index for s in sel.audio] == [1, 2, 3, 4]
    assert sel.default_subtitle is None  # Japanese is understood too


def test_a_film_in_a_language_nobody_prefers_shows_the_first_preferred_subtitles():
    probe = parse_probe(JAPANESE_FILM)
    sel = select_streams(probe, "ja", TrackPolicy(languages=("fr", "en")))
    assert sel.default_audio.index == 2
    assert sel.default_subtitle is not None and sel.default_subtitle.index == 7  # no French


def test_all_subtitles_and_no_subtitles():
    probe = parse_probe(ENGLISH_FILM)
    every = select_streams(probe, "en", TrackPolicy(subtitles="all"))
    assert [s.index for s in every.subtitles] == [5, 6, 7, 8]
    none = select_streams(probe, "en", TrackPolicy(subtitles="none"))
    assert none.subtitles == () and none.forced_subtitle is None
    assert _kept(none) == [0, 1, 2, 4]
    assert "-c:s" not in _args(none)


def test_a_disc_with_no_preferred_sound_keeps_its_first_track():
    probe = parse_probe(_probe(_s(0, "video", "mpeg2video"), _s(1, "audio", "ac3", "ita")))
    sel = select_streams(probe, "fr", TrackPolicy(languages=("de",)))
    assert [s.index for s in sel.audio] == [1]
