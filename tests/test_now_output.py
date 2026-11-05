"""Inline "Show output" on Now (#33): the rip card and the running Encoding row carry a
collapsed toggle over the last ~20 lines of their running Step, kept live, with a link to
that Step in Logs. The real app with fakes."""

from __future__ import annotations

import html
import re

from ama.drive import DiscType
from ama.jobs import JobStatus
from tests.conftest import eventually


def _tail(page: str, tail_id: str) -> str:
    m = re.search(rf'<div class="log tail" id="{tail_id}".*?</div>', page, re.S)
    assert m, f"no tail {tail_id}"
    return m.group(0)


def _ripping(harness) -> int:
    harness.drive.insert(DiscType.BD, "EXAMPLE_MOVIE")
    eventually(lambda: harness.makemkv.ripping)  # held at 50%: no more lines
    eventually(lambda: harness.services.video_rip.progress is not None)
    return harness.services.video_rip.job.id


def test_the_rip_card_has_a_collapsed_output_toggle_over_the_rip_steps_tail(client, harness):
    job = _ripping(harness)
    step = harness.services.runs.job_step(job)
    for n in range(30):
        harness.services.runs.line(step, f"makemkv line {n}")
    page = html.unescape(client.get("/").text)
    foot = re.search(r'<div class="out-sum">.*?</div>', page, re.S).group(0)
    assert "makemkvcon" in foot
    assert f'aria-controls="tail-{step}"' in foot and 'aria-expanded="false"' in foot
    assert "Show output" in foot
    assert f'href="/logs/jobs/{job}#step-rip"' in foot and "Open in Logs" in foot
    tail = _tail(page, f"tail-{step}")
    assert " hidden" in tail.split(">", 1)[0] and 'role="log"' in tail
    assert "makemkv line 29" in tail and "makemkv line 10" in tail
    assert "makemkv line 9\n" not in tail and "makemkv line 9<" not in tail  # last 20 only


def test_the_running_encoding_row_has_a_toggle_linking_to_its_encode_step(client, harness):
    harness.web.add_film("Example Movie", 1234, "Example Movie", runtime=122)
    harness.ffmpeg.hold = True
    harness.makemkv.release()
    harness.drive.insert(DiscType.BD, "EXAMPLE_MOVIE")
    eventually(lambda: harness.ffmpeg.encoding.is_set())
    job = harness.services.jobs.list(JobStatus.RIPPED)[0].id
    step = harness.services.runs.job_step(job)
    harness.services.jobs.step_output(job, "Stream mapping: from ffmpeg")
    page = html.unescape(client.get("/").text)
    bin_ = re.search(r'<section class="bin enc.*?</section>', page, re.S).group(0)
    row = re.search(r'<div class="rowout">.*?</div>', bin_, re.S).group(0)
    assert f'aria-controls="tail-{step}"' in row and "Show output" in row
    assert f'href="/logs/jobs/{job}#step-encode-1"' in row
    assert "Stream mapping: from ffmpeg" in _tail(bin_, f"tail-{step}")
    assert bin_.count('class="rowout"') == 1


def test_an_open_tail_fetches_its_newest_lines_live(client, harness):
    job = _ripping(harness)
    step = harness.services.runs.job_step(job)
    harness.services.runs.line(step, "first line")
    harness.services.runs.line(step, "a line with <b>markup</b>")
    live = client.get("/now/output", params={"steps": f"{step},99999"})
    assert live.status_code == 200
    assert f'id="tail-{step}" hx-swap-oob="innerHTML"' in live.text
    assert "a line with &lt;b&gt;markup&lt;/b&gt;" in live.text
    assert "tail-99999" not in live.text
    assert client.get("/now/output", params={"steps": "x"}).text.strip() == ""


def test_the_cd_rip_card_has_the_toggle_too(client, harness):
    harness.cyanrip.hold_at = 2
    harness.drive.insert(DiscType.CD, "AUDIO_CD")
    eventually(lambda: harness.services.cd.current is not None)
    job = harness.services.cd.current.job_id
    step = harness.services.runs.job_step(job)
    page = html.unescape(client.get("/").text)
    foot = re.search(r'<div class="out-sum">.*?</div>', page, re.S).group(0)
    assert "cyanrip" in foot and f'href="/logs/jobs/{job}#step-rip"' in foot
    assert f'id="tail-{step}"' in page


def test_the_job_page_rip_card_has_no_toggle(client, harness):
    job = _ripping(harness)
    assert "out-sum" not in client.get(f"/jobs/{job}").text
