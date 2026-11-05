"""The restart banner's buttons: restart now, warn while busy, restart when idle (#37)."""

from __future__ import annotations

import html
import time

import pytest
from fastapi.testclient import TestClient

from ama.app import create_app
from ama.drive import DiscType
from tests.conftest import eventually, make_harness, write_config


@pytest.fixture
def setup(tmp_path):
    h = make_harness(tmp_path, config_file=write_config(tmp_path))
    with TestClient(create_app(h.services)) as c:
        c.post("/settings/general", data={"web.host": "0.0.0.0", "web.port": "8081"})
        yield c, h


def _page(client, path="/settings/general"):
    r = client.get(path)
    assert r.status_code == 200, path
    return html.unescape(r.text)


def _hold_a_cd_rip(h):
    h.cyanrip.hold_at = 2
    h.drive.insert(DiscType.CD, "ARRIVAL")
    h.cyanrip.wait_until_held()


def test_restart_now_when_idle_restarts_and_waits_for_the_new_server(setup):
    client, h = setup
    assert "Restart now" in _page(client)
    r = client.post("/restart", data={"back": "/settings/general"})
    assert r.status_code == 200
    assert h.services.restart.requested
    page = html.unescape(r.text)
    assert "Restarting AMA" in page
    assert "http://testserver:8081/settings/general" in page  # where it comes back
    boot = client.get("/boot")
    assert boot.json()["boot"] and boot.headers["access-control-allow-origin"] == "*"


def test_restart_while_a_rip_runs_warns_first(setup):
    client, h = setup
    _hold_a_cd_rip(h)
    page = _page(client)
    assert "<b>ARRIVAL</b> is Ripping" in page and "Restart…" in page
    r = client.post("/restart", data={"back": "/settings/general"}, follow_redirects=False)
    assert r.headers["location"] == "/settings/general?restart=confirm"
    assert not h.services.restart.requested
    page = _page(client, r.headers["location"])
    assert "A Rip is running" in page and "Restart when idle" in page
    client.post("/restart", data={"back": "/settings/general", "force": "1"})
    assert h.services.restart.requested
    h.cyanrip.release()


def test_restart_when_idle_holds_new_rips_and_restarts_once_the_rip_is_done(setup):
    client, h = setup
    _hold_a_cd_rip(h)
    client.post("/restart/when-idle", data={"back": "/settings/general"})
    page = _page(client)
    assert "AMA restarts when nothing is Ripping or Encoding" in page
    assert "Waiting for <b>ARRIVAL</b> to finish Ripping" in page
    assert not h.services.restart.requested
    h.cyanrip.release()
    eventually(lambda: h.services.restart.requested)
    rips = len(h.cyanrip.calls)
    h.drive.eject()
    h.drive.insert(DiscType.CD, "ANOTHER")
    time.sleep(0.5)
    assert len(h.cyanrip.calls) == rips  # no new Rip once a restart is under way


def test_dont_restart_after_all(setup):
    client, h = setup
    _hold_a_cd_rip(h)
    client.post("/restart/when-idle", data={"back": "/settings/general"})
    client.post("/restart/cancel", data={"back": "/settings/general"})
    assert "Restart…" in _page(client)
    h.cyanrip.release()
    eventually(lambda: h.services.cd.current is None)
    time.sleep(1.2)  # past the Restarter's check
    assert not h.services.restart.requested


def test_the_boot_id_is_open_without_signing_in(tmp_path):
    h = make_harness(tmp_path, password="secret")
    with TestClient(create_app(h.services)) as client:
        assert client.get("/boot", follow_redirects=False).status_code == 200
        assert client.post("/restart", follow_redirects=False).headers["location"] == "/login"
