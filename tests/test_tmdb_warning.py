"""Now warns that film/TV Identification is off while the TMDB key is empty (#73)."""

from __future__ import annotations

import html

from fastapi.testclient import TestClient

from ama.app import create_app
from tests.conftest import eventually, make_harness
from tests.test_problems import _rip

WARNING = "Film/TV Identification is off until you add a TMDB key"


def test_with_no_key_now_warns_and_links_to_settings(tmp_path):
    h = make_harness(tmp_path, tmdb_key="")
    with TestClient(create_app(h.services)) as c:
        page = c.get("/").text
        assert WARNING in page
        warning = page[page.index(WARNING) - 400:page.index(WARNING) + 600]
        assert 'href="/settings/archive/identification"' in warning


def test_with_a_key_there_is_no_warning(client):
    assert WARNING not in client.get("/").text


def test_dismissing_hides_it_and_adding_a_key_removes_it(tmp_path):
    h = make_harness(tmp_path, tmdb_key="")
    app = create_app(h.services)
    with TestClient(app) as c, TestClient(app) as other_browser:
        r = c.post("/notices/tmdb-off/dismiss")
        assert r.status_code == 200 and r.request.url.path == "/"
        assert WARNING not in r.text and WARNING not in c.get("/").text

        assert WARNING in other_browser.get("/").text
        h.services.tmdb.api_key = "tmdb-key"  # the key is set (Settings, #26)
        assert WARNING not in other_browser.get("/").text


def test_with_no_key_and_a_film_waiting_there_is_one_tmdb_warning(tmp_path):
    h = make_harness(tmp_path, tmdb_key="")
    h.web.add_film("Example Movie", 1234, "Example Movie", runtime=122)
    with TestClient(create_app(h.services)) as c:
        _rip(h)
        eventually(lambda: h.services.problems.banners())
        page = html.unescape(c.get("/").text)
        assert page.count(WARNING) == 1 and "No TMDB API key, so" not in page
        warning = page[page.index(WARNING):page.index('class="split"')]
        assert "carry on by themselves" in warning
        ripping = page[page.index('id="ripping-h"'):page.index('id="encoding-h"')]
        assert "Waiting: No TMDB API key is set" in ripping  # the card still says why
