"""Discord and ntfy notifications (#15): the real app with fake Discord/ntfy endpoints."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from ama.app import create_app
from ama.discs import DiscStatus
from ama.drive import DiscType
from tests.conftest import Harness, eventually, make_harness

WEBHOOK = "https://discord.com/api/webhooks/123/secret-token"
DONE = "Disc done · insert the next one"


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
    assert notified.services.discs.list(DiscStatus.RIPPED)[0].label == "KID_A"


def test_a_disc_needing_review_notifies_both_channels(notified):
    notified.web.musicbrainz[notified.cyanrip.disc_id] = 404  # MusicBrainz doesn't know it
    notified.drive.insert(DiscType.CD, "MYSTERY")
    _sent(notified, 2)

    assert _titles(notified) == ([DONE, "Review needed"],) * 2
    assert "MYSTERY" in _ntfy(notified)[1]["message"]
    assert "Review" in _discord(notified)[1]["embeds"][0]["description"]


def test_a_failed_disc_notifies_both_channels_with_what_went_wrong(notified):
    notified.cyanrip.read_errors_in = 2
    notified.drive.insert(DiscType.CD, "SCRATCHED")
    _sent(notified, 1)

    rec = notified.services.discs.list(DiscStatus.FAILED)[0]
    assert _titles(notified) == (["Disc failed"], ["Disc failed"])
    assert rec.failure and rec.failure.headline in _ntfy(notified)[0]["message"]
    assert rec.failure.headline in _discord(notified)[0]["embeds"][0]["description"]


def test_discarding_a_rip_in_review_is_not_a_failure_to_report(app):
    h, client = app
    h.web.musicbrainz[h.cyanrip.disc_id] = 404
    h.drive.insert(DiscType.CD)
    _sent(h, 2)
    rec = h.services.discs.list(DiscStatus.REVIEW)[0]

    client.post(f"/review/{rec.id}/discard", follow_redirects=False)
    eventually(lambda: h.services.discs.get(rec.id).status == DiscStatus.FAILED)
    time.sleep(0.3)
    assert _titles(h) == ([DONE, "Review needed"],) * 2


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
        eventually(lambda: len(h.services.discs.list(DiscStatus.RIPPED)) == 1)
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
    notified.drive.insert(DiscType.CD, "SECOND")
    eventually(lambda: len(notified.services.discs.list(DiscStatus.RIPPED)) == 2)
    gate.set()
