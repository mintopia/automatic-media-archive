"""cyanrip output parsing, against real output captured from users' runs (tests/data/cyanrip/,
source URL on each file's first line) plus format-string-built lines where no capture exists."""

from __future__ import annotations

from pathlib import Path

import pytest

from ama.cyanrip import ArResult, ArStatus, Progress, parse_progress, parse_report, rip_succeeded

DATA = Path(__file__).parent / "data" / "cyanrip"


def capture(name: str) -> str:
    return (DATA / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("line, expected", [
    ("Ripping and encoding track 13, progress - 100.00%, ETA - 0s   ", Progress(13, 100.0, 0, 0)),
    ("Ripping and encoding track 1, progress - 26.83%, ETA - 35m ", Progress(1, 26.83, 35 * 60, 0)),
    ("Ripping track 1, progress - 100.00%, ETA - 38m   ", Progress(1, 100.0, 38 * 60, 0)),
    ("Ripping and encoding track 7, progress - 45.10%, ETA - 1h 4m, errors - 3",
     Progress(7, 45.1, 3840, 3)),
    ("Track 13 ripped and encoded successfully!", None),
])
def test_progress_lines(line, expected):
    assert parse_progress(line) == expected


def test_progress_lines_in_real_stdout_are_recognised():
    lines = capture("stdout-progress-repeat-issue51.txt").splitlines()
    parsed = [p for p in map(parse_progress, lines) if p]
    assert len(parsed) == 7
    assert parsed[-1] == Progress(1, 26.83, 35 * 60, 0)


def test_accurate_log_gives_every_track_verified_with_best_confidence():
    r = parse_report(capture("log-accurate-issue93.txt"))
    assert r.disc_tracks == 18
    assert r.disc_id == "iV4zYu5_g1huHgbfxS6qgxQBL_A-"
    assert r.accuraterip == "found"
    assert r.ripping_errors == 0
    tracks = r.audio_tracks
    assert [t.number for t in tracks] == list(range(1, 19))
    assert all(t.ripped for t in tracks)
    # Track 1: v1 confidence 11, v2 confidence 17 -> 17. Track 14: v1 9, v2 16 -> 16.
    assert tracks[0].ar == ArResult(ArStatus.ACCURATE, 17)
    assert tracks[13].ar == ArResult(ArStatus.ACCURATE, 16)
    assert tracks[0].seconds == pytest.approx(8584800 / 44100)  # 3:14.67
    assert not any(t.preemphasis for t in tracks)
    assert rip_succeeded(r, 0, 18)


def test_disc_in_database_but_tracks_unmatched_is_a_mismatch_and_data_track_is_ignored():
    r = parse_report(capture("log-arnotfound-datatrack-issue125.txt"))
    assert r.tracks[13].is_data
    audio = r.audio_tracks
    assert [t.number for t in audio] == list(range(1, 13))
    assert all(t.ar == ArResult(ArStatus.MISMATCH) for t in audio)
    assert r.ripping_errors == 0
    assert rip_succeeded(r, 0, 12)


def test_terminal_stdout_with_progress_parses_like_the_log():
    r = parse_report(capture("stdout-progress-issue93.txt"))
    assert r.disc_tracks == 13
    assert r.tracks[13].ripped
    assert r.tracks[13].ar == ArResult(ArStatus.ACCURATE, 30)
    assert r.ripping_errors == 0


def test_media_changed_run_is_not_a_success():
    r = parse_report(capture("stdout-mediachanged-issue113.txt"))
    assert r.accuraterip == "not found"
    assert not r.audio_tracks
    assert not rip_succeeded(r, 0, 13)


def test_disc_not_in_accuraterip():
    r = parse_report("AccurateRip:    not found\n\nTrack 1 ripped and encoded successfully!\n"
                     "  Accurip:       not found\n    Accurip v1:  1DFFB9BC\n")
    assert r.tracks[1].ar == ArResult(ArStatus.NOT_IN_DB)


def test_accuraterip_lookup_error_is_no_verdict():
    r = parse_report("AccurateRip:    error\n\nTrack 1 ripped and encoded successfully!\n"
                     "  Accurip:       not found\n")
    assert r.tracks[1].ar == ArResult(ArStatus.UNAVAILABLE)


# No public capture of `-I` output, a hidden track or pre-emphasis exists: these use the exact
# format strings from cyanrip 0.9.3.1 (cyanrip_main.c setup_track_offsets_and_report,
# cyanrip_log.c cyanrip_log_track_end).
INFO = """\
Disc tracks:    3
AccurateRip:    found

Gaps:
    2850 frame unmarked gap between lead-in and track 1, marking as a pregap
    2850 frame pregap in track 1, splitting off into a new track, number 0

Track 0 info:
  Preemphasis:   none detected

  Properties:
    Duration:    00:00:38.000
    Samples:     1675800
    Frames:      2850

Track 1 info:
  Preemphasis:   present (TOC)

  Properties:
    Duration:    00:04:44.000
    Samples:     12524400

Track 2 info:
  Preemphasis:   present (subcode)

  Properties:
    Samples:     441000

Track 3 info:
  Preemphasis:   none detected

  Properties:
    Data bytes:  11665920 (11.13 Mib)
    Frames:      4960
"""


def test_info_output_gives_toc_with_hidden_track_preemphasis_and_data_track():
    r = parse_report(INFO)
    assert r.htoa_frames == 2850
    assert [(t.number, round(t.seconds), t.preemphasis) for t in r.audio_tracks] == [
        (0, 38, False), (1, 284, True), (2, 10, True)]
    assert r.tracks[3].is_data
    assert not any(t.ripped for t in r.audio_tracks)


def test_success_needs_exit_zero_clean_footer_and_every_track():
    r = parse_report(capture("log-accurate-issue93.txt"))
    assert not rip_succeeded(r, 1, 18)
    assert not rip_succeeded(r, 0, 19)
    errors = parse_report(capture("log-accurate-issue93.txt").replace("Ripping errors: 0",
                                                                         "Ripping errors: 2"))
    assert not rip_succeeded(errors, 0, 18)


def test_info_output_gives_the_discs_mcn_from_the_real_ffvii_toc():
    r = parse_report(capture("info-ffvii-rebirth-disc1.txt"))
    assert r.mcn == "4988601470865"
    assert parse_report(INFO).mcn is None
