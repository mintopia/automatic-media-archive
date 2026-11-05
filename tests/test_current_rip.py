"""One "current Rip" view: the Now drive card and the Ripping bin read it, so they agree (#20)."""

import html
import re

import pytest

from ama.drive import DiscType
from ama.web import render_fragment
from tests.conftest import eventually

PHASES = ("Ripping", "Review", "Encoding", "Filed", "Failed")


def _frag(harness, name: str) -> str:
    return html.unescape(render_fragment(name, harness.services))


def _chips(fragment: str) -> list[str]:
    return re.findall(r'class="stk[^"]*"[^>]*>([^<]*)<', fragment)


def _bin_rows(harness) -> list[str]:
    return re.findall(r'<div class="row compact">.*?</div></div>', _frag(harness, "ripping"))


@pytest.mark.parametrize("disc_type", [DiscType.DVD, DiscType.BD, DiscType.UHD])
def test_a_video_rip_is_a_row_in_the_ripping_bin_with_its_progress(client, harness, disc_type):
    harness.drive.insert(disc_type, "HEAT_DISC1")
    eventually(lambda: "Title 1 of 2" in _frag(harness, "ripping"))
    rows = _bin_rows(harness)
    assert len(rows) == 1
    assert f'<div class="dtype">{disc_type.value}</div>' in rows[0]
    assert re.search(r"Title 1 of 2 · \d+%", rows[0])
    assert 'Ripping <span class="c">1</span>' in _frag(harness, "ripping")
    assert "Nothing ripping." not in _frag(harness, "ripping")
    harness.makemkv.release()
    eventually(lambda: harness.drive.ejected == 1)


def test_a_video_rip_shows_the_same_phase_and_progress_on_the_drive_card_and_in_the_bin(client, harness):
    harness.drive.insert(DiscType.BD, "EXAMPLE_MOVIE")
    eventually(lambda: "Title 1 of 2" in _frag(harness, "ripping"))
    eventually(lambda: harness.makemkv.ripping)  # held at 50%: progress stops moving
    eventually(lambda: "Title 1 of 2 · 0%" not in _frag(harness, "ripping"))
    drive, ripping = _frag(harness, "drive"), _frag(harness, "ripping")
    assert _chips(drive) == _chips(ripping) == ["Ripping"]
    pct = re.search(r"Title 1 of 2 · (\d+)%", ripping).group(1)
    assert f'<div class="pct">{pct}%</div>' in drive
    harness.makemkv.release()
    eventually(lambda: harness.drive.ejected == 1)


def test_a_cd_is_in_the_ripping_bin_while_its_track_list_is_read(client, harness):
    harness.cyanrip.hold_toc = True
    harness.drive.insert(DiscType.CD)
    harness.cyanrip.wait_until_held()
    eventually(lambda: harness.services.cd.reading_toc)
    drive, ripping = _frag(harness, "drive"), _frag(harness, "ripping")
    rows = _bin_rows(harness)
    assert len(rows) == 1 and '<div class="dtype">CD</div>' in rows[0]
    assert "Starting" in rows[0]
    assert "Nothing ripping." not in ripping
    assert _chips(drive) == _chips(ripping) == ["Ripping"]
    harness.cyanrip.release()
    eventually(lambda: harness.drive.ejected == 1)


def test_a_ripping_cd_shows_the_same_phase_and_track_on_the_drive_card_and_in_the_bin(client, harness):
    harness.cyanrip.hold_at = 2
    harness.drive.insert(DiscType.CD)
    harness.cyanrip.wait_until_held()
    eventually(lambda: harness.services.cd.current is not None
               and harness.services.cd.current.tracks[1].percent == 50.0)
    drive, ripping = _frag(harness, "drive"), _frag(harness, "ripping")
    rows = _bin_rows(harness)
    assert len(rows) == 1 and "Track 2 of 3" in rows[0]
    assert "Track 2 of 3" in drive
    assert _chips(drive) == _chips(ripping) == ["Ripping"]
    harness.cyanrip.release()
    eventually(lambda: harness.drive.ejected == 1)


def test_the_ripping_bin_is_empty_when_nothing_rips(harness):
    assert _bin_rows(harness) == []
    assert "Nothing ripping." in _frag(harness, "ripping")


def test_every_status_chip_in_the_templates_is_a_phase():
    from ama.web import HERE
    for path in (HERE / "templates").rglob("*.html"):
        for chip in re.findall(r'class="stk[^"{]*"[^>]*>([^<{]*)<', path.read_text("utf-8")):
            assert chip in PHASES, f"{path.name}: status chip {chip!r} isn't a Phase"
