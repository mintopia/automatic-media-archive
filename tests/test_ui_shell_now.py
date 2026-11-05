"""The shell (skip link, menu, live Review count) and the Now page's headings and live status."""

import httpx
from fastapi.testclient import TestClient

from ama.app import create_app
from ama.drive import DiscType
from ama import web
from ama.web import TEMPLATES, fragments_for
from tests.conftest import eventually, make_harness
from tests.test_web_now import _read_event


def test_every_page_has_a_skip_link_and_a_theme_menu(client):
    page = client.get("/").text
    assert '<a class="skip" href="#content">Skip to content</a>' in page
    assert '<div id="content" tabindex="-1">' in page
    assert '<summary class="mbtn" aria-label="Menu">' in page
    for theme in ("system", "light", "dark"):
        assert f'data-theme-set="{theme}"' in page
    assert "Log out" not in page  # no password, nothing to log out of


def test_now_has_an_h1_and_its_bins_are_headings(client):
    page = client.get("/").text
    assert '<h1 class="sr">Now</h1>' in page
    for h in ("ripping-h", "encoding-h", "filed-h", "rev-h"):
        assert f'id="{h}"' in page
    assert page.count('<h2 class="tab') >= 3 and '<h2 class="tab-h" id="filed-h">' in page
    assert 'aria-live="polite">' not in page.split('sse-swap="drive"')[1].split(">")[0]


def test_an_idle_now_marks_every_bin_empty_and_has_the_quiet_line(client):
    page = client.get("/").text
    assert page.count(' empty" aria-labelledby') == 4
    assert "Nothing ripping, encoding or waiting for you." in page


def test_the_review_count_and_drive_status_are_their_own_live_fragments(live_server, harness):
    assert "review-count" in fragments_for("review")
    assert "drive-status" in fragments_for("drive")
    with httpx.stream("GET", f"{live_server}/events", timeout=5) as r:
        lines = r.iter_lines()
        assert "Insert a Disc" in _read_event(lines, "drive-status")
        harness.drive.insert(DiscType.DVD, "HEAT_DISC1")
        while "HEAT_DISC1" not in (status := _read_event(lines, "drive-status")):
            pass
        assert status.startswith(("Ripping HEAT_DISC1", "HEAT_DISC1 is in the drive"))
        harness.makemkv.release()


def test_scratch_page_marks_scratch_current_not_now(client):
    page = client.get("/scratch").text
    assert 'href="/" aria-current' not in page
    assert 'class="scratch" href="/scratch" title="Local scratch space" aria-current="page"' in page


def test_with_a_password_the_menu_logs_out(tmp_path):
    h = make_harness(tmp_path, password="hunter2")
    with TestClient(create_app(h.services), follow_redirects=False) as c:
        c.post("/login", data={"password": "hunter2"})
        assert "Log out" in c.get("/").text
        r = c.post("/logout")
        assert r.status_code == 303 and r.headers["location"] == "/login"
        assert c.get("/").status_code == 303


def test_pages_registered_in_the_menu_sit_between_theme_and_log_out(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "MENU", [("Settings", "/settings", "settings")])
    h = make_harness(tmp_path, password="hunter2")
    with TestClient(create_app(h.services)) as c:
        c.post("/login", data={"password": "hunter2"})
        page = c.get("/").text
    menu = page.split('<div class="mpanel">')[1].split("</details>")[0]
    settings = ('<a class="mi" href="/settings"><svg class="i" aria-hidden="true">'
                '<use href="/static/icons.svg#settings"/></svg>Settings</a>')
    assert menu.index('data-theme-set="dark"') < menu.index(settings) < menu.index("Log out")
    assert 'href="/settings"' not in page.split('<nav class="nav"')[1].split("</nav>")[0]


def test_a_menu_page_is_marked_current_on_itself_and_its_subpages(harness, monkeypatch):
    monkeypatch.setattr(web, "MENU", [("Settings", "/settings", "settings")])
    base = TEMPLATES.env.get_template("base.html")
    ctx = web.view_context(harness.services)
    assert 'href="/settings" aria-current="page"' in base.render(ctx | {"current": "/settings/nas"})
    assert 'href="/settings" aria-current' not in base.render(ctx | {"current": "/"})
    assert 'href="/settings" aria-current' not in base.render(ctx | {"current": "/settingsx"})


def test_sign_in_page_has_no_inline_styles(tmp_path):
    h = make_harness(tmp_path, password="hunter2")
    with TestClient(create_app(h.services), follow_redirects=False) as c:
        assert 'style="' not in c.get("/login").text
        assert 'style="' not in c.post("/login", data={"password": "no"}).text


def test_encoding_progress_is_a_progressbar():
    src = TEMPLATES.env.loader.get_source(TEMPLATES.env, "partials/encoding_bin.html")[0]
    assert 'role="progressbar" aria-valuenow="{{ job.progress.pct }}"' in src


def test_scratch_says_when_the_space_in_use_is_other_files(client, harness):
    harness.disk.used = 220 * 1000**3
    page = client.get("/scratch").text
    assert "220 of 256 GB in use" in page
    assert "None of it is Rips: it's other files on this drive." in page.replace("&#39;", "'")
    assert "No Rips are on scratch. The 220 GB in use is other files on this drive." in page


def test_a_video_rip_is_not_called_nothing_ripping(client, harness):
    harness.drive.insert(DiscType.DVD, "HEAT_DISC1")
    eventually(lambda: "is ripping in the drive" in client.get("/").text)
    assert "Nothing ripping." not in client.get("/").text
    harness.makemkv.release()
