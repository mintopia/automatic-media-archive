"""Archive › Encode in Settings (#28, ADR 0010): only encoders that pass a test encode
can be picked, every option saves to ama.toml and applies to the next Encode, and a
configured encoder that stops working is flagged here and in the tools banner."""

from __future__ import annotations

import html
import re

import pytest
from fastapi.testclient import TestClient

from ama.app import create_app
from ama.encoder_probe import ProbeUntested
from tests.conftest import eventually, make_harness, write_config

PAGE = "/settings/archive/encode"
FORM = {"encode.encoder": "hevc_nvenc", "encode.speed": "slower", "encode.cq.dvd": "20",
        "encode.cq.bd": "22", "encode.cq.uhd": "24", "encode.max_resolution.dvd": "keep",
        "encode.max_resolution.bd": "keep", "encode.max_resolution.uhd": "keep",
        "encode.audio": "languages", "encode.subtitles": "languages",
        "encode.languages": "English"}


@pytest.fixture
def setup(tmp_path):
    toml = write_config(tmp_path)
    h = make_harness(tmp_path, config_file=toml)
    h.ffmpeg.broken_encoders = {"av1_nvenc", "hevc_qsv"}  # like the RTX 3060 Ti box
    with TestClient(create_app(h.services)) as c:
        _tested(h)
        yield c, toml, h


def _tested(h) -> None:
    eventually(lambda: not any(isinstance(s, ProbeUntested)
                               for s in h.services.encoders.states.values()))


def _page(client, path=PAGE) -> str:
    r = client.get(path)
    assert r.status_code == 200
    return html.unescape(r.text)


def _radio(page: str, value: str) -> str:
    m = re.search(rf'<label class="radio[^"]*">\s*<input type="radio" name="encode.encoder" '
                  rf'value="{value}"[^>]*>.*?</label>', page, re.S)
    assert m, value
    return m.group(0)


def test_the_encode_page_offers_only_encoders_that_passed_their_test(setup):
    client, _, _ = setup
    page = _page(client)
    nvenc, av1, qsv, x265 = (_radio(page, v) for v in
                             ("hevc_nvenc", "av1_nvenc", "hevc_qsv", "libx265"))
    assert "checked" in nvenc and "disabled" not in nvenc and "Fast; the default" in nvenc
    for na in (av1, qsv):
        assert "disabled" in na and 'class="radio na"' in na and "Not available on this PC" in na
    assert "disabled" not in x265 and "very slow for UHD" in x265
    speeds = re.findall(r"<option[^>]*>([^<]+)</option>",
                        page[page.index('id="encode-speed"'):].split("</select>")[0])
    assert speeds == ["Faster, bigger", "Balanced", "Slower, smaller", "Slowest, smallest"]
    assert '<option value="slower" selected>' in page
    assert "Max resolution" in page and "Keep (2160p)" in page and ">720p<" in page
    assert "Now: quality 20 to 24 · sound in English · subtitles in English" in page
    assert "stopped working" not in page


def test_every_encode_option_saves_to_the_file_and_applies_to_the_next_encode(setup):
    client, toml, h = setup
    tests_before = len(h.ffmpeg.probes)
    r = client.post(PAGE, data=FORM | {
        "encode.encoder": "libx265", "encode.speed": "balanced", "encode.cq.uhd": "18",
        "encode.max_resolution.uhd": "1080p", "encode.audio": "first_plus_stereo",
        "encode.subtitles": "none", "encode.languages": "Japanese, English"},
        follow_redirects=False)
    assert r.status_code == 303
    text = toml.read_text(encoding="utf-8")
    for line in ('encoder = "libx265"', 'speed = "balanced"', "uhd = 18",
                 'uhd = "1080p"', 'audio = "first_plus_stereo"', 'subtitles = "none"',
                 'languages = "Japanese, English"'):
        assert line in text, line
    cfg = h.services.movie_archive.encoder.cfg
    assert (cfg.encoder, cfg.speed, cfg.cq.uhd, cfg.max_resolution.uhd) == (
        "libx265", "balanced", 18, "1080p")
    assert cfg.preferred_languages == ("ja", "en")
    eventually(lambda: len(h.ffmpeg.probes) >= tests_before + 4)  # tested again on save
    page = _page(client, r.headers["location"])
    assert "Saved at" in page
    assert "Now: quality 18 to 22 · first sound track plus stereo · no subtitles" in page
    assert "Restart AMA" not in page  # all of it is live


def test_an_encoder_that_failed_its_test_cant_be_saved(setup):
    client, toml, _ = setup
    before = toml.read_bytes()
    r = client.post(PAGE, data=FORM | {"encode.encoder": "av1_nvenc"})
    assert r.status_code == 422
    assert "didn't pass its test encode" in html.unescape(r.text)
    assert toml.read_bytes() == before


def test_unknown_preferred_languages_get_a_field_message(setup):
    client, toml, _ = setup
    before = toml.read_bytes()
    r = client.post(PAGE, data=FORM | {"encode.languages": "English, Klingon"})
    assert r.status_code == 422
    page = html.unescape(r.text)
    assert 'href="#encode-languages"' in page and "AMA doesn't know Klingon" in page
    assert toml.read_bytes() == before


def test_a_configured_encoder_that_stops_working_is_flagged_and_can_be_tested_again(setup):
    client, _, h = setup
    assert "stopped working" not in _page(client, "/")
    h.ffmpeg.broken_encoders.add("hevc_nvenc")
    r = client.post(PAGE + "/test-encoders", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == PAGE
    page = _page(client)
    assert "HEVC (NVIDIA) stopped working" in page
    assert "Encodes will fail until it works again or you pick another encoder" in page
    nvenc = _radio(page, "hevc_nvenc")
    assert "broken" in nvenc and "checked" in nvenc and "Stopped working at the" in nvenc
    assert "Test encoders again" in page
    now = _page(client, "/")  # the tools banner
    assert "HEVC (NVIDIA) stopped working" in now and f'href="{PAGE}"' in now
    h.ffmpeg.broken_encoders.discard("hevc_nvenc")
    client.post(PAGE + "/test-encoders")
    assert "stopped working" not in _page(client, "/")
