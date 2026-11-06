"""Discord and ntfy notifications (#15): the real app with fake Discord/ntfy endpoints."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from datetime import datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from ama.app import create_app
from ama.events import EventBus
from ama.notify import Discord, Event, Notification, Notifier, Ntfy
from ama.problems import Problem, Problems
from ama.jobs import Failure, FailureKind, JobStatus, TitleRecord, TitleStatus
from ama.drive import DiscType
from tests.conftest import Harness, eventually, make_harness
from tests.test_cd_archive import DISC_1, SPECIAL, _insert, _response

WEBHOOK = "https://discord.com/api/webhooks/123/secret-token"
DONE = "Rip done · insert the next one"


@pytest.fixture
def app(tmp_path) -> Iterator[tuple[Harness, TestClient]]:
    """The app running with both channels configured."""
    h = make_harness(tmp_path, discord=WEBHOOK, ntfy_topic="ama-test-topic")
    with TestClient(create_app(h.services)) as c:
        yield h, c


@pytest.fixture
def notified(app) -> Harness:
    return app[0]


def _discord(h: Harness) -> list[dict]:
    return [json.loads(r.content) for r in h.web.discord]


def _ntfy(h: Harness) -> list[dict]:
    return [json.loads(r.content) for r in h.web.ntfy]


def _titles(h: Harness) -> tuple[list[str], list[str]]:
    return ([m["embeds"][0]["title"] for m in _discord(h)], [m["title"] for m in _ntfy(h)])


def _sent(h: Harness, n: int) -> None:
    eventually(lambda: len(h.web.discord) == n and len(h.web.ntfy) == n)


def _channels_used(h: Harness) -> set[str]:
    return {n for n in ("discord", "ntfy") if getattr(h.web, n)}


def test_a_finished_rip_says_insert_the_next_disc_on_both_channels(notified):
    notified.drive.insert(DiscType.CD, "KID_A")
    _sent(notified, 1)

    discord, ntfy = _discord(notified)[0], _ntfy(notified)[0]
    assert discord["embeds"][0]["title"] == DONE
    assert "KID_A" in discord["embeds"][0]["description"]
    assert ntfy["title"] == DONE
    assert "KID_A" in ntfy["message"]
    assert notified.services.jobs.list(JobStatus.RIPPED)[0].label == "KID_A"


def test_a_disc_needing_review_notifies_both_channels(notified):
    notified.web.musicbrainz[notified.cyanrip.mb_disc_id] = 404  # MusicBrainz doesn't know it
    notified.drive.insert(DiscType.CD, "MYSTERY")
    _sent(notified, 2)

    assert _titles(notified) == ([DONE, "Review needed"],) * 2
    assert "MYSTERY" in _ntfy(notified)[1]["message"]
    assert "Review" in _discord(notified)[1]["embeds"][0]["description"]


def test_a_failed_disc_notifies_both_channels_with_what_went_wrong(notified):
    notified.cyanrip.read_errors_in = 2
    notified.drive.insert(DiscType.CD, "SCRATCHED")
    _sent(notified, 1)

    rec = notified.services.jobs.list(JobStatus.FAILED)[0]
    assert _titles(notified) == (["Job failed"], ["Job failed"])
    assert rec.failure and rec.failure.headline in _ntfy(notified)[0]["message"]
    assert rec.failure.headline in _discord(notified)[0]["embeds"][0]["description"]


def test_discarding_a_rip_in_review_is_not_a_failure_to_report(app):
    h, client = app
    h.web.musicbrainz[h.cyanrip.mb_disc_id] = 404
    h.drive.insert(DiscType.CD)
    _sent(h, 2)
    rec = h.services.jobs.list(JobStatus.REVIEW)[0]

    client.post(f"/review/{rec.id}/discard", follow_redirects=False)
    eventually(lambda: h.services.jobs.get(rec.id).status == JobStatus.FAILED)
    time.sleep(0.3)
    assert _titles(h) == ([DONE, "Review needed"],) * 2


def test_cancelling_a_job_is_not_a_failure_to_report(app):
    h, client = app
    h.cyanrip.hold_at = 2
    h.drive.insert(DiscType.CD, "KID_A")
    h.cyanrip.wait_until_held()
    rec = h.services.jobs.list(JobStatus.RIPPING)[0]
    client.post(f"/jobs/{rec.id}/cancel", follow_redirects=False)
    h.cyanrip.release()
    eventually(lambda: h.services.jobs.get(rec.id).status == JobStatus.FAILED)
    time.sleep(0.3)
    assert _titles(h) == ([], [])


def test_a_job_whose_scratch_was_cleaned_up_is_a_failure_to_report(notified):
    jobs = notified.services.jobs
    old = jobs.create(DiscType.BD, "OLD_FILM", "video")
    jobs.mark_ripped(old.id)
    jobs.mark_scratch_cleaned(old.id, Failure(FailureKind.SCRATCH_CLEANED, "Scratch cleaned up",
                                              "Insert the Disc again to rip it again."))
    notified.drive.insert(DiscType.CD, "KID_A")  # any bus event makes the notifier look

    eventually(lambda: "Job failed" in _titles(notified)[1])
    assert any("OLD_FILM" in m["message"] for m in _ntfy(notified) if m["title"] == "Job failed")


def test_the_messages_are_safe_well_formed_requests(notified):
    notified.drive.insert(DiscType.CD, "@everyone")
    _sent(notified, 1)

    discord, ntfy = notified.web.discord[0], notified.web.ntfy[0]
    assert str(discord.url) == WEBHOOK + "?wait=true"  # so a dropped message is an error
    assert json.loads(discord.content)["allowed_mentions"] == {"parse": []}
    assert str(ntfy.url) == "https://ntfy.sh/"  # JSON publish: the topic is in the body
    body = json.loads(ntfy.content)
    assert body["topic"] == "ama-test-topic" and body["tags"] == ["white_check_mark"]


@pytest.mark.parametrize("discord, topic, sent_to", [
    ("", "", set()),
    (WEBHOOK, "", {"discord"}),
    ("", "ama-test-topic", {"ntfy"}),
])
def test_a_channel_without_its_config_value_is_off(tmp_path, caplog, discord, topic, sent_to):
    h = make_harness(tmp_path, discord=discord, ntfy_topic=topic)
    with TestClient(create_app(h.services)):
        h.drive.insert(DiscType.CD)
        eventually(lambda: len(h.services.jobs.list(JobStatus.RIPPED)) == 1)
        eventually(lambda: _channels_used(h) == sent_to)
        time.sleep(0.3)
    assert _channels_used(h) == sent_to
    assert not [r for r in caplog.records if r.name == "ama.notify"]


@pytest.mark.parametrize("status", [0, 404, 500])  # 0 = no network
def test_a_notification_failure_never_blocks_the_pipeline(notified, caplog, status):
    notified.web.notify_status = status
    notified.drive.insert(DiscType.CD, "FIRST")
    _sent(notified, 1)
    eventually(lambda: notified.drive.ejected == 1)

    notified.web.notify_status = 200  # the next Disc still rips, and still notifies
    notified.cyanrip.mb_disc_id = "O75dAncJZ7onpacHCAgF4NqupdA-"  # another CD, not a repeat
    notified.drive.insert(DiscType.CD, "SECOND")
    _sent(notified, 2)
    assert "SECOND" in _ntfy(notified)[1]["message"]
    warnings = [r.getMessage() for r in caplog.records if r.name == "ama.notify"]
    assert len(warnings) == 2  # one per channel, for FIRST
    assert not any("secret-token" in w or "ama-test-topic" in w for w in warnings)


def test_a_channel_that_hangs_never_holds_up_the_next_rip(notified, monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(notified.services.notifier.channels[0], "send",
                        lambda note: gate.wait(10))
    notified.drive.insert(DiscType.CD, "FIRST")
    eventually(lambda: notified.drive.ejected == 1)
    notified.cyanrip.mb_disc_id = "O75dAncJZ7onpacHCAgF4NqupdA-"  # another CD, not a repeat
    notified.drive.insert(DiscType.CD, "SECOND")
    eventually(lambda: len(notified.services.jobs.list(JobStatus.RIPPED)) == 2)
    gate.set()


def test_each_channel_gives_up_after_10_seconds_on_its_own():
    timeouts = []

    def answer(request):
        timeouts.append(request.extensions["timeout"])
        return httpx.Response(200, json={})

    http = httpx.Client(transport=httpx.MockTransport(answer), timeout=30)
    note = Notification(Event.RIP_DONE, DONE, "Insert the next Disc.")
    Discord(http, WEBHOOK).send(note)
    Ntfy(http, "https://ntfy.sh", "ama-test-topic").send(note)
    assert [set(t.values()) for t in timeouts] == [{10}, {10}]


def test_a_hanging_channel_never_delays_the_others(notified, monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(notified.services.notifier.channels[0], "send",
                        lambda note: gate.wait(10))
    notified.drive.insert(DiscType.CD, "KID_A")
    try:
        eventually(lambda: len(notified.web.ntfy) == 1, timeout=5)
    finally:
        gate.set()
    assert notified.web.discord == []


def test_a_failed_channel_is_named_in_the_problem_while_the_others_deliver(harness):
    class Down:
        name = "Discord"

        def send(self, note):
            raise OSError("no network")

    class Up:
        name = "ntfy"

        def __init__(self):
            self.sent = []

        def send(self, note):
            self.sent.append(note)

    problems = Problems(EventBus(), now=lambda: datetime(2026, 11, 5, 21, 40))
    up = Up()
    Notifier(harness.services.jobs, EventBus(), [Down(), up], problems).send(
        [Notification(Event.RIP_DONE, DONE, "Insert the next Disc.")])
    [banner] = problems.banners()
    assert banner.problem == Problem.NOTIFY and banner.detail == "Discord: OSError"
    assert len(up.sent) == 1


def test_filing_a_job_notifies_both_channels_with_what_it_was_filed_as(notified):
    _insert(notified, DISC_1, 24, _response(only=SPECIAL))
    _sent(notified, 2)

    rec = notified.services.jobs.list(JobStatus.FILED)[0]
    assert _titles(notified) == ([DONE, "Filed"],) * 2
    assert rec.title in _ntfy(notified)[1]["message"]
    assert rec.title in _discord(notified)[1]["embeds"][0]["description"]
    assert _ntfy(notified)[1]["tags"] == ["file_folder"]


def test_a_job_filed_with_no_titles_in_it_sends_no_filed_alert(notified):
    jobs = notified.services.jobs
    empty = jobs.create(DiscType.BD, "ALL_SKIPPED", "empty")
    jobs.set_titles(empty.id, [TitleRecord(1, 0, 3600, 1, 1, 0, "", "t1.mkv",
                                           status=TitleStatus.SKIPPED)], 0, 0)
    jobs.mark_ripped(empty.id)
    jobs.mark_filed(empty.id, "Nothing", notified.libraries_root / "Nothing")
    _insert(notified, DISC_1, 24, _response(only=SPECIAL))
    eventually(lambda: "Filed" in _titles(notified)[0] and "Filed" in _titles(notified)[1])
    time.sleep(0.3)

    filed = [m["message"] for m in _ntfy(notified) if m["title"] == "Filed"]
    filed += [m["embeds"][0]["description"] for m in _discord(notified)
              if m["embeds"][0]["title"] == "Filed"]
    assert len(filed) == 2 and not any("ALL_SKIPPED" in m for m in filed)
