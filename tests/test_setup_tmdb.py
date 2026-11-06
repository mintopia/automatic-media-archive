"""Setup's TMDB key step (#73, ADR 0016): checked live against (a fake) TMDB, or skipped."""

from __future__ import annotations

import html
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from ama.config import load_config
from ama.setup import Setup, create_setup_app
from ama.setup.steps import tmdb_key

GOOD = "good-key"


@pytest.fixture
def asked(monkeypatch) -> list[httpx.Request]:
    """A fake TMDB that knows one v3 key; what it was asked."""
    requests: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path != "/3/authentication":
            return httpx.Response(404)
        if request.url.params.get("api_key") == GOOD:
            return httpx.Response(200, json={"success": True})
        return httpx.Response(401, json={"success": False, "status_code": 7})

    monkeypatch.setattr(tmdb_key, "client",
                        lambda: httpx.Client(transport=httpx.MockTransport(answer)))
    return requests


@pytest.fixture
def setup(tmp_path, monkeypatch) -> Setup:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    return Setup(tmp_path / "AMA" / "ama.toml")


@pytest.fixture
def client(setup) -> TestClient:
    return TestClient(create_setup_app(setup))


def _finish(client: TestClient) -> None:
    r = client.post("/setup/ready")
    assert r.status_code == 200 and "Starting AMA" in r.text, r.text


def test_the_tmdb_step_comes_after_where_things_go_and_offers_to_skip(client):
    page = html.unescape(client.get("/setup/tmdb").text)
    steps = page.split('class="setup-steps"', 1)[1].split("</ol>", 1)[0]
    assert steps.index("Where things go") < steps.index("TMDB") < steps.index("Ready")
    assert 'name="tmdb_key"' in page and "Skip — CDs only for now" in page


def test_a_good_key_is_checked_with_tmdb_and_written_to_the_settings_file(client, setup, asked):
    r = client.post("/setup/tmdb", data={"tmdb": "key", "tmdb_key": f"  {GOOD} "})
    assert r.request.url.path != "/setup/tmdb" and r.status_code == 200
    assert [q.url.path for q in asked] == ["/3/authentication"]
    _finish(client)
    assert load_config(setup.config).tmdb.api_key == GOOD


def test_a_bad_key_is_named_and_setup_stays_on_the_step(client, setup, asked):
    r = client.post("/setup/tmdb", data={"tmdb": "key", "tmdb_key": "typo"})
    assert r.status_code == 422
    page = html.unescape(r.text)
    assert "<h1>TMDB key</h1>" in page and "TMDB didn't accept this key" in page
    assert 'aria-invalid="true"' in page


def test_no_key_counts_as_skipping(client, setup, asked):
    r = client.post("/setup/tmdb", data={"tmdb": "key", "tmdb_key": ""})
    assert r.request.url.path == "/setup/remote"
    assert "Skipped — CDs only for now" in html.unescape(client.get("/setup/ready").text)
    _finish(client)
    assert asked == [] and load_config(setup.config).tmdb.api_key == ""


def test_tmdb_out_of_reach_says_so_and_skipping_still_works(client, setup, monkeypatch):
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no network")

    monkeypatch.setattr(tmdb_key, "client",
                        lambda: httpx.Client(transport=httpx.MockTransport(down)))
    r = client.post("/setup/tmdb", data={"tmdb": "key", "tmdb_key": GOOD})
    assert r.status_code == 422 and "Couldn't reach TMDB" in html.unescape(r.text)
    assert client.post("/setup/tmdb", data={"tmdb": "skip", "tmdb_key": GOOD}).status_code == 200


def test_skipping_writes_no_key_and_asks_tmdb_nothing(client, setup, asked):
    r = client.post("/setup/tmdb", data={"tmdb": "skip", "tmdb_key": "half-typed"})
    assert r.status_code == 200 and r.request.url.path == "/setup/remote"
    assert "Skipped — CDs only for now" in html.unescape(client.get("/setup/ready").text)
    _finish(client)
    assert asked == [] and load_config(setup.config).tmdb.api_key == ""


def test_the_key_never_shows_on_the_ready_step(client, asked):
    client.post("/setup/tmdb", data={"tmdb": "key", "tmdb_key": GOOD})
    ready = client.get("/setup/ready").text.split("<h1>Ready</h1>", 1)[1]
    assert GOOD not in ready and "TMDB" in ready
