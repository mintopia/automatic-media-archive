"""Picture analysis for the Encode (#10): progressive output and auto-crop.

Parsers run against real ffmpeg 9.0.2 output (tests/data/ffmpeg, see its README).
"""

from pathlib import Path

import pytest

from ama import picture
from ama.picture import Crop, Scan

DATA = Path(__file__).parent / "data" / "ffmpeg"


def sample(name: str) -> list[str]:
    return (DATA / f"sample-{name}.txt").read_text(encoding="utf-8").splitlines()


def samples(*names: str) -> list[picture.Sample]:
    return [picture.parse_sample(sample(n)) for n in names]


NTSC = 30000 / 1001


@pytest.mark.parametrize("name, scan", [
    ("telecined", Scan.TELECINED),
    ("telecined-busy", Scan.TELECINED),
    ("interlaced", Scan.INTERLACED),
    ("progressive", Scan.PROGRESSIVE),
    ("progressive-busy", Scan.PROGRESSIVE),  # combed-looking but no steady field order
    ("black", Scan.PROGRESSIVE),
])
def test_the_scan_type_is_read_from_idet(name, scan):
    assert picture.scan_type(samples(name, name), NTSC).scan == scan


def test_the_field_order_comes_from_idet():
    assert picture.scan_type(samples("telecined"), NTSC).order == "tff"


def test_telecine_on_a_pal_rate_source_is_deinterlaced_not_decimated():
    assert picture.scan_type(samples("telecined"), 25.0).scan == Scan.INTERLACED


def box(w, h, x, y) -> picture.Sample:
    return picture.Sample(picture.Fields(), Crop(w, h, x, y))


def test_a_letterboxed_source_is_cropped_to_the_picture():
    found = samples("telecined", "telecined-busy", "progressive", "progressive-busy")
    assert picture.crop_for(found, 720, 480) == Crop(720, 360, 0, 60)


def test_dark_and_black_scenes_do_not_shrink_the_crop():
    found = samples("dark-scene", "black", "telecined", "dark-scene", "progressive", "black")
    assert picture.crop_for(found, 720, 480) == Crop(720, 360, 0, 60)


def test_a_film_that_is_dark_in_every_sample_is_not_cropped():
    # boxes that never line up are scene content, not bars
    found = [box(120, 80, 300, 200), box(400, 300, 100, 90), box(500, 200, 90, 150)]
    assert picture.crop_for(found, 720, 480) is None


def test_a_static_dark_scene_in_every_sample_is_not_cropped():
    # the boxes agree, but no real bars leave only a sliver of the picture
    assert picture.crop_for(samples("dark-scene", "dark-scene", "black"), 720, 480) is None


def test_a_full_frame_source_is_not_cropped():
    assert picture.crop_for(samples("interlaced", "interlaced"), 720, 480) is None


def test_thin_bars_are_left_alone_and_wide_ones_cropped_per_axis():
    found = [box(704, 476, 8, 2), box(704, 476, 8, 2)]  # 16 px of side bars, 4 px top/bottom
    assert picture.crop_for(found, 720, 480) == Crop(704, 480, 8, 0)


def test_the_crop_is_widened_to_even_sizes_and_offsets():
    found = [box(1920, 801, 0, 139), box(1920, 801, 0, 139)]
    assert picture.crop_for(found, 1920, 1080) == Crop(1920, 802, 0, 138)


def test_the_tallest_frame_of_a_variable_aspect_film_is_kept():
    found = [box(1920, 800, 0, 140), box(1920, 800, 0, 140),
             box(1920, 1040, 0, 20), box(1920, 1040, 0, 20)]  # IMAX scenes
    assert picture.crop_for(found, 1920, 1080) == Crop(1920, 1040, 0, 20)


def test_samples_are_spread_over_the_feature_skipping_its_ends():
    times = picture.sample_times(6000.0)
    assert len(times) == picture.SAMPLES
    assert times[0] >= 300 and times[-1] <= 5700 - 10
    assert times == sorted(times)
    assert picture.sample_times(0.0) == [0.0]


def test_a_sample_runs_idet_only_when_asked():
    args = picture.sample_args(Path("ffmpeg.exe"), Path("t.mkv"), 600.0, idet=True)
    assert args[:1] == ["ffmpeg.exe"] and args[-3:] == ["-f", "null", "-"]
    assert args[args.index("-ss") + 1] == "600.000" and args.index("-ss") < args.index("-i")
    assert args[args.index("-vf") + 1] == f"idet,{picture.CROPDETECT}"
    args = picture.sample_args(Path("ffmpeg.exe"), Path("t.mkv"), 600.0, idet=False)
    assert args[args.index("-vf") + 1] == picture.CROPDETECT


# These chains were run through ffmpeg 9.0.2 + hevc_nvenc on the synthetic sources:
# the telecined one came out 1439 progressive frames at 24000/1001 for 60 s,
# the interlaced one 3596 frames at 60000/1001.
@pytest.mark.parametrize("scan, crop, chain", [
    (picture.ScanResult(Scan.TELECINED, "tff"), Crop(720, 360, 0, 60),
     "fieldmatch=order=tff:combmatch=full,bwdif=mode=send_frame:parity=auto:deint=interlaced,"
     "decimate,crop=720:360:0:60"),
    (picture.ScanResult(Scan.INTERLACED, "bff"), None,
     "bwdif=mode=send_field:parity=auto:deint=all"),
    (picture.ScanResult(Scan.PROGRESSIVE), Crop(1920, 800, 0, 140), "crop=1920:800:0:140"),
    (picture.ScanResult(Scan.PROGRESSIVE), None, None),
])
def test_the_filter_chain_detelecines_or_deinterlaces_before_cropping(scan, crop, chain):
    assert picture.Picture(scan, crop, 1920, 1080).filters == chain


def test_analyse_reads_scan_and_crop_from_the_samples():
    runs = [sample("telecined"), sample("dark-scene"), sample("telecined-busy")]
    pic = picture.analyse(runs, width=720, height=480, fps=NTSC, detect_scan=True)
    assert pic.scan.scan == Scan.TELECINED and pic.crop == Crop(720, 360, 0, 60)
    assert "telecined" in pic.describe() and "720x360" in pic.describe()


def test_scan_detection_is_skipped_when_not_asked():
    pic = picture.analyse([sample("interlaced")] * 2, width=720, height=480, fps=NTSC,
                          detect_scan=False)
    assert pic.scan.scan == Scan.PROGRESSIVE and pic.filters is None
