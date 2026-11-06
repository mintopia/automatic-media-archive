"""The Webhook alert channel (#52): the real app posting to a fake endpoint."""

from __future__ import annotations

import html
import json
import socket
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from ama.app import create_app
from ama.config import secret_values
from ama.drive import DiscType
from ama.jobs import JobStatus
from ama.config import WebConfig
from ama.notify import Event, Notification, Webhook, ui_address
from tests.conftest import Harness, eventually, make_harness, write_config
from tests.test_cd_archive import DISC_1, SPECIAL, _insert, _response

URL = "https://hooks.example/ama/url-secret"
HEADER = "header-secret-value"


@pytest.fixture
def app(tmp_path) -> Iterator[tuple[Harness, TestClient]]:
    toml = write_config(tmp_path, extra=f"""
[webhook]
url = "{URL}"
header_name = "X-Ama-Token"
header_value = "{HEADER}"
""")
    h = make_harness(tmp_path, config_file=toml)
    with TestClient(create_app(h.services)) as c:
        yield h, c


def _posts(h: Harness) -> list[dict]:
    return [json.loads(r.content) for r in h.web.webhook]


def test_a_finished_rip_posts_versioned_json_about_the_job(app):
    h, _ = app
    h.drive.insert(DiscType.CD, "KID_A")
    eventually(lambda: len(h.web.webhook) == 1)

    request = h.web.webhook[0]
    assert request.method == "POST" and str(request.url) == URL
    assert request.headers["X-Ama-Token"] == HEADER
    body = _posts(h)[0]
    rec = h.services.jobs.list(JobStatus.RIPPED)[0]
    assert body["version"] == 1 and body["event"] == "rip_done"
    assert datetime.fromisoformat(body["at"]).utcoffset().total_seconds() == 0
    assert body["at"].endswith("Z")
    assert body["job"] == {"id": rec.id, "disc_type": "cd", "title": "KID_A",
                           "status": "ripped",
                           "url": f"http://{socket.gethostname()}:8080/jobs/{rec.id}"}


def test_archiving_posts_job_archived_with_what_it_was_archived_as(app):
    h, _ = app
    _insert(h, DISC_1, 24, _response(only=SPECIAL))
    eventually(lambda: [p["event"] for p in _posts(h)] == ["rip_done", "job_archived"])

    rec = h.services.jobs.list(JobStatus.ARCHIVED)[0]
    job = _posts(h)[1]["job"]
    assert job["status"] == "archived" and job["title"] == rec.title and job["id"] == rec.id


def test_set_under_alerts_it_applies_at_once_and_its_secrets_stay_on_the_server(tmp_path):
    toml = write_config(tmp_path)
    h = make_harness(tmp_path, config_file=toml)
    with TestClient(create_app(h.services)) as client:
        assert "Webhook" in client.get("/settings/alerts").text
        r = client.post("/settings/alerts", data={
            "webhook.url": URL, "webhook.header_name": "X-Ama-Token",
            "webhook.header_value": HEADER, "ntfy.url": "https://ntfy.sh"},
            follow_redirects=False)
        assert r.status_code == 303
        assert [c.name for c in h.services.notifier.channels] == ["Webhook"]
        page = client.get("/settings/alerts").text
        assert URL not in page and HEADER not in page and "X-Ama-Token" in page
        assert {URL, HEADER} <= set(secret_values(h.services.config))

        h.drive.insert(DiscType.CD, "KID_A")
        eventually(lambda: len(h.web.webhook) == 1)
        assert h.web.webhook[0].headers["X-Ama-Token"] == HEADER


def test_send_test_posts_a_test_event_and_says_how_it_went(app):
    h, client = app
    r = client.post("/settings/alerts/webhook-test")
    assert r.status_code == 200 and "Test alert sent" in r.text
    [body] = _posts(h)
    assert body["event"] == "test" and body["job"] is None and body["version"] == 1

    h.web.notify_status = 404
    page = html.unescape(client.post("/settings/alerts/webhook-test").text)
    assert "Couldn't send the test alert: HTTP 404" in page
    assert URL not in page and HEADER not in page


def test_send_test_without_a_saved_url_says_to_save_one(tmp_path):
    h = make_harness(tmp_path, config_file=write_config(tmp_path))
    with TestClient(create_app(h.services)) as client:
        page = html.unescape(client.post("/settings/alerts/webhook-test").text)
    assert "Save a webhook URL first" in page


@pytest.mark.parametrize("event", list(Event))
def test_every_alert_is_one_post_that_gives_up_after_10_seconds(event):
    seen = []

    def answer(request):
        seen.append((request.extensions["timeout"], json.loads(request.content)))
        return httpx.Response(204)

    http = httpx.Client(transport=httpx.MockTransport(answer), timeout=30)
    at = datetime(2026, 11, 5, 13, 0, tzinfo=timezone(timedelta(hours=1)))
    Webhook(http, URL, "http://ama:8080").send(Notification(event, "t", "m", at=at))
    [(timeout, body)] = seen
    assert set(timeout.values()) == {10}
    assert body == {"version": 1, "event": event.value, "at": "2026-11-05T12:00:00Z",
                    "job": None}


@pytest.mark.parametrize("host, link", [("192.168.1.20", "http://192.168.1.20:8080"),
                                        ("fe80::1", "http://[fe80::1]:8080"),
                                        ("ama.local", "http://ama.local:8080")])
def test_the_job_link_is_a_valid_address_for_an_ipv6_host(host, link):
    assert ui_address(WebConfig(host=host, port=8080)) == link
