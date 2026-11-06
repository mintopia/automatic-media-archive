"""Setup's "Reach AMA from other devices?" step (ADR 0016): the host, and an optional password."""

from __future__ import annotations

import html
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ama.app import create_app
from ama.config import load_config
from ama.setup import Setup, create_setup_app
from tests.conftest import make_harness


@pytest.fixture
def setup(tmp_path, monkeypatch) -> Setup:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    return Setup(tmp_path / "AMA" / "ama.toml")


@pytest.fixture
def client(setup) -> TestClient:
    return TestClient(create_setup_app(setup))


def _finish(client: TestClient, **remote: str):
    """Answer the remote step with `remote`, then press Finish on Ready."""
    r = client.post("/setup/remote", data=remote)
    assert r.request.url.path == "/setup/ready", r.text
    return client.post("/setup/ready")


def test_the_step_comes_just_before_ready_and_defaults_to_yes(client):
    page = client.get("/setup/remote").text
    assert "<h1>Reach AMA from other devices?</h1>" in page
    assert re_checked(page) == "yes"
    assert 'type="password"' in page and "recommended" in page.lower()
    steps = page.split('class="setup-steps"', 1)[1].split("</ol>", 1)[0]
    assert steps.index("Reach AMA from other devices?") < steps.index("Ready")


def re_checked(page: str) -> str:
    """The `remote` answer the page has ticked."""
    return re.search(r'<input[^>]*name="remote"[^>]*value="(\w+)"[^>]*checked', page)[1]


def test_yes_writes_the_any_address_host(client, setup):
    _finish(client, remote="yes", password="")
    cfg = load_config(setup.config)
    assert (cfg.web.host, cfg.web.password) == ("0.0.0.0", "")


def test_no_writes_localhost_and_ignores_a_password(client, setup):
    r = _finish(client, remote="no", password="hunter2")
    cfg = load_config(setup.config)
    assert (cfg.web.host, cfg.web.password) == ("127.0.0.1", "")
    assert "ama_session" not in r.cookies


def test_the_password_is_stored_as_the_web_password(client, setup):
    _finish(client, remote="yes", password="hunter2")
    assert load_config(setup.config).web.password == "hunter2"


def test_ready_lists_the_choice_but_never_the_password(client):
    client.post("/setup/remote", data={"remote": "yes", "password": "hunter2"})
    page = html.unescape(client.get("/setup/ready").text)
    assert "Other devices" in page and "hunter2" not in page
    assert "Password" in page


def test_an_unknown_answer_is_refused(client):
    r = client.post("/setup/remote", data={"remote": "maybe", "password": ""})
    assert r.status_code == 422 and r.request.url.path == "/setup/remote"


def test_after_setup_with_a_password_the_browser_is_signed_in(client, setup, tmp_path):
    r = _finish(client, remote="yes", password="hunter2")
    assert r.status_code == 200 and "Starting AMA" in r.text
    h = make_harness(tmp_path, config_file=setup.config)  # AMA, started from the new file
    with TestClient(create_app(h.services), follow_redirects=False) as stranger:
        assert stranger.get("/").status_code == 303  # a stranger must sign in
    with TestClient(create_app(h.services), follow_redirects=False,
                    cookies=dict(client.cookies)) as ama:
        assert ama.get("/").status_code == 200  # the browser that ran Setup is in


def test_after_setup_without_a_password_ama_is_open(client, setup, tmp_path):
    _finish(client, remote="yes", password="")
    h = make_harness(tmp_path, config_file=setup.config)
    with TestClient(create_app(h.services), follow_redirects=False) as ama:
        assert ama.get("/").status_code == 200


def test_going_back_keeps_the_answer(client):
    client.post("/setup/remote", data={"remote": "no", "password": ""})
    assert re_checked(client.get("/setup/remote").text) == "no"
