"""The Settings page: edits ama.toml section by section (#26, ADR 0008)."""

import asyncio
import html
from collections import Counter

import pytest
from fastapi.testclient import TestClient

from ama.app import create_app
from ama.settings import is_live, keys
from ama.web.settings_sections import SECTIONS
from tests.conftest import MAKEMKV_OK, make_harness, write_config

SECRETS = {"password": "pa55word-secret", "tmdb": "tmdb-secret-key", "plex": "plex-secret-token",
           "discord": "https://discord.com/api/webhooks/99/discord-secret",
           "ntfy": "ntfy-secret-topic"}


@pytest.fixture
def setup(tmp_path):
    toml = write_config(tmp_path, extra=f"""
[discord]
webhook_url = "{SECRETS['discord']}"

[ntfy]
url = "https://ntfy.sh"
topic = "{SECRETS['ntfy']}"
""")
    text = toml.read_text(encoding="utf-8")
    toml.write_text(text.replace('api_key = "tmdb-key"', f'api_key = "{SECRETS["tmdb"]}"')
                    .replace('token = "plex-token"', f'token = "{SECRETS["plex"]}"'),
                    encoding="utf-8")
    h = make_harness(tmp_path, config_file=toml)
    with TestClient(create_app(h.services)) as c:
        yield c, toml, h.services


def _page(client, path):
    r = client.get(path)
    assert r.status_code == 200, path
    return html.unescape(r.text)


def test_every_setting_has_exactly_one_field_on_the_page():
    on_page = Counter(k for s in SECTIONS for k in s.keys())
    assert set(on_page) == set(keys())
    assert [k for k, n in on_page.items() if n > 1] == []


def test_groups_that_say_changes_apply_at_once_hold_only_live_keys():
    for s in SECTIONS:
        for g in s.groups:
            assert g.live == all(is_live(k) for k in g.keys()), (s.slug, g.title)


def test_settings_opens_on_general_and_shows_the_file(setup):
    client, _, _ = setup
    r = client.get("/settings", follow_redirects=False)
    assert r.status_code in (302, 303, 307) and r.headers["location"] == "/settings/general"
    page = _page(client, "/settings/general")
    assert 'value="0.0.0.0"' in page and 'value="8080"' in page
    for tab in ("General", "Ripping", "Archive", "Alerts"):
        assert f">{tab}</a>" in page
    assert "Save General" in page
    assert "Used after a restart" in page


def test_the_menu_links_to_settings(setup):
    client, _, _ = setup
    assert 'href="/settings"' in client.get("/").text


def test_secrets_never_render_back(setup):
    client, toml, _ = setup
    client.post("/settings/general", data={"web.password": SECRETS["password"]})
    assert SECRETS["password"] in toml.read_text(encoding="utf-8")
    pages = [_page(client, f"/settings/{s.slug}") for s in SECTIONS]
    # A rejected save doesn't echo a typed secret either.
    r = client.post("/settings/alerts", data={"discord.webhook_url": "api/webhooks/1234-typed",
                                              "ntfy.url": "https://ntfy.sh"})
    assert r.status_code == 422
    pages.append(html.unescape(r.text))
    for page in pages:
        for secret in SECRETS.values():
            assert secret not in page
        assert "1234-typed" not in page
    identification = _page(client, "/settings/archive/identification")
    assert "Set" in identification and "Replace" in identification and "Remove" in identification


def test_saving_writes_the_file_and_says_when(setup):
    client, toml, services = setup
    r = client.post("/settings/ripping", data={"drive.letter": "", "drive.poll_seconds": "0.01",
                                               "cd.offset": "48", "cd.retries": "10"},
                    follow_redirects=False)
    assert r.status_code == 303
    assert "offset = 48\n" in toml.read_text(encoding="utf-8")
    assert toml.with_name("ama.toml.bak").exists()
    page = _page(client, r.headers["location"])
    assert "Saved at" in page and 'value="48"' in page
    assert services.cd.cfg.offset == 48
    assert "Restart AMA" not in page  # a live key needs no restart


def test_invalid_input_gets_a_field_message_and_the_file_is_unchanged(setup):
    client, toml, _ = setup
    before = toml.read_bytes()
    r = client.post("/settings/alerts", data={"discord.webhook_url": "api/webhooks/1234",
                                              "ntfy.url": "ntfy.sh"})
    assert r.status_code == 422
    page = html.unescape(r.text)
    assert "Alerts weren't saved" in page and "<code>ama.toml</code> hasn't changed" in page
    assert 'href="#ntfy-url"' in page and 'href="#discord-webhook_url"' in page
    assert "Enter a full address starting with https:// or http://" in page
    assert "Paste the whole webhook URL" in page
    assert 'aria-invalid="true"' in page
    assert 'value="ntfy.sh"' in page  # a non-secret mistake stays in the box to fix
    assert toml.read_bytes() == before


def test_restart_keys_show_the_banner_and_a_waiting_tag(setup):
    client, toml, services = setup
    client.post("/settings/general", data={"web.host": "0.0.0.0", "web.port": "8081"})
    assert "port = 8081" in toml.read_text(encoding="utf-8")
    assert services.config.web.port == 8080
    page = _page(client, "/settings/general")
    assert "Restart AMA to use 1 saved change" in page
    assert "Port (General)" in page
    assert "Waiting for restart" in page
    assert "Restart AMA to use 1 saved change" in _page(client, "/settings/alerts")


def test_a_secret_is_replaced_removed_or_kept(setup):
    client, toml, services = setup
    client.post("/settings/archive/identification", data={"tmdb.api_key": ""})
    assert SECRETS["tmdb"] in toml.read_text(encoding="utf-8")  # empty box = keep
    client.post("/settings/archive/identification", data={"tmdb.api_key": "replaced"})
    assert services.tmdb.api_key == "replaced"
    client.post("/settings/archive/identification", data={"remove": "tmdb.api_key"})
    assert 'api_key = ""' in toml.read_text(encoding="utf-8")
    assert services.tmdb.api_key == ""
    page = _page(client, "/settings/archive/identification")
    assert "Not set" in page


def test_a_section_saves_only_its_own_keys(setup):
    client, toml, _ = setup
    before = toml.read_text(encoding="utf-8")
    r = client.post("/settings/general", data={"cd.offset": "1", "web.port": "8080"},
                    follow_redirects=False)
    assert r.status_code == 303
    assert toml.read_text(encoding="utf-8") == before


def test_a_hand_edit_shows_on_the_page(setup):
    client, toml, _ = setup
    toml.write_text(toml.read_text(encoding="utf-8").replace("retries = 10", "retries = 33"),
                    encoding="utf-8")
    assert 'value="33"' in _page(client, "/settings/ripping")


def test_save_and_go_lands_on_the_next_section_only(setup):
    client, _, _ = setup
    r = client.post("/settings/general", data={"web.port": "8080", "next": "/settings/alerts"},
                    follow_redirects=False)
    assert r.headers["location"] == "/settings/alerts"
    r = client.post("/settings/general", data={"web.port": "8080", "next": "https://evil"},
                    follow_redirects=False)
    assert r.headers["location"].startswith("/settings/general?saved=")


def _drive_select(page: str) -> str:
    start = page.index('name="drive.letter"')
    return page[start:page.index("</select>", start)]


def test_the_drive_is_picked_from_the_optical_drives_windows_reports(tmp_path):
    h = make_harness(tmp_path, config_file=write_config(tmp_path))
    h.drive.optical = ("D:", "E:")
    with TestClient(create_app(h.services)) as client:
        select = _drive_select(_page(client, "/settings/ripping"))
    assert '<option value="" selected>Automatic (first drive found)</option>' in select
    assert '<option value="D:">D:</option>' in select
    assert '<option value="E:">E:</option>' in select


def test_a_saved_drive_that_is_gone_stays_selected_and_saves_as_a_letter(tmp_path):
    toml = write_config(tmp_path)
    toml.write_text(toml.read_text(encoding="utf-8").replace('letter = ""', 'letter = "f"'),
                    encoding="utf-8")
    h = make_harness(tmp_path, config_file=toml)
    with TestClient(create_app(h.services)) as client:
        select = _drive_select(_page(client, "/settings/ripping"))
        assert '<option value="F:" selected>F: (not found)</option>' in select
        assert '<option value="D:">D:</option>' in select
        client.post("/settings/ripping", data={"drive.letter": "D:", "drive.poll_seconds": "0.01",
                                               "cd.offset": "667", "cd.retries": "10"})
    assert 'letter = "D:"\n' in toml.read_text(encoding="utf-8")


def test_a_drive_makemkv_has_seen_shows_its_name(tmp_path):
    h = make_harness(tmp_path, config_file=write_config(tmp_path))
    h.drive.optical = ("D:", "E:")
    h.makemkv_check["output"] = MAKEMKV_OK + (
        'DRV:0,0,999,0,"BD-RE PIONEER BD-RW  BDR-S11JX 1.53 NFDL016192WL","","D:"\n'
        'DRV:1,256,999,0,"","",""\n')
    asyncio.run(h.services.tools.check_makemkv())
    with TestClient(create_app(h.services)) as client:
        select = _drive_select(_page(client, "/settings/ripping"))
    assert '<option value="D:">D: · BD-RE PIONEER BD-RW BDR-S11JX 1.53 NFDL016192WL</option>' \
        in select
    assert '<option value="E:">E:</option>' in select


def test_unknown_section_is_404(setup):
    client, _, _ = setup
    assert client.get("/settings/nope").status_code == 404
