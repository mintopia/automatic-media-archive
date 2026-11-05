import pytest
from fastapi.testclient import TestClient

from ama.app import create_app
from tests.conftest import make_harness


@pytest.fixture
def locked(tmp_path):
    h = make_harness(tmp_path, password="hunter2")
    with TestClient(create_app(h.services), follow_redirects=False) as c:
        yield c


def test_without_a_password_the_ui_is_open(client):
    assert client.get("/").status_code == 200
    assert client.get("/login", follow_redirects=False).status_code == 303


def test_with_a_password_pages_redirect_to_sign_in(locked):
    r = locked.get("/")
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert locked.get("/events").status_code == 401
    assert locked.get("/static/ama.css").status_code == 200  # sign-in page needs styles
    assert "Sign in" in locked.get("/login").text


def test_wrong_password_is_refused_with_a_message(locked):
    r = locked.post("/login", data={"password": "nope"})
    assert r.status_code == 401
    assert "That password didn't work" in r.text
    assert locked.get("/").status_code == 303


def test_right_password_signs_in(locked):
    r = locked.post("/login", data={"password": "hunter2"})
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert locked.get("/").status_code == 200


def test_sign_in_survives_a_restart_but_not_a_password_change(tmp_path):
    h = make_harness(tmp_path, password="hunter2")
    with TestClient(create_app(h.services), follow_redirects=False) as c:
        c.post("/login", data={"password": "hunter2"})
        cookies = dict(c.cookies)

    h2 = make_harness(tmp_path, password="hunter2")  # same state db
    with TestClient(create_app(h2.services), follow_redirects=False, cookies=cookies) as c:
        assert c.get("/").status_code == 200

    h3 = make_harness(tmp_path, password="changed")
    with TestClient(create_app(h3.services), follow_redirects=False, cookies=cookies) as c:
        assert c.get("/").status_code == 303
