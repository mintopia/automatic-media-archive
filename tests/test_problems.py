"""Why a Job can't move on (#40): per-Job Waiting lines and app-wide banners."""

from __future__ import annotations

import asyncio
import html
import threading
import time
from datetime import datetime

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from ama.app import create_app
from ama.discs import DiscStatus
from ama.drive import DiscType
from ama.config import PlexConfig
from ama.events import EventBus, Topic
from ama.notify import Event, Notification, Notifier
from ama.plex import Plex
from ama.problems import Problem, Problems
from tests.conftest import eventually, make_harness
from tests.test_web_now import _read_event

NOW = datetime(2026, 11, 5, 21, 40, 0)


def _published(bus: EventBus, act) -> set[str]:
    async def go() -> set[str]:
        with bus.subscribe() as q:
            act()
            seen = set()
            while not q.empty():
                seen.add(q.get_nowait())
            return seen
    return asyncio.run(go())


def test_a_jobs_blocking_reason_is_kept_until_it_moves_on():
    bus = EventBus()
    problems = Problems(bus, now=lambda: NOW)

    seen = _published(bus, lambda: problems.waiting(3, "The NAS isn't connected", 120))
    waiting = problems.why(3)
    assert waiting is not None and waiting.reason == "The NAS isn't connected"
    assert waiting.retry_at == datetime(2026, 11, 5, 21, 42, 0)
    assert {Topic.RIP, Topic.ENCODE, Topic.PROBLEMS} <= seen  # cards and banners re-render
    assert problems.why(4) is None

    seen = _published(bus, lambda: problems.moved_on(3))
    assert problems.why(3) is None
    assert Topic.PROBLEMS in seen
    assert _published(bus, lambda: problems.moved_on(3)) == set()  # nothing changed


def test_a_job_waiting_on_an_app_wide_cause_raises_one_banner_until_every_job_moves_on():
    problems = Problems(EventBus(), now=lambda: NOW)
    key = "No TMDB API key is set in ama.toml ([tmdb] api_key)"
    problems.waiting(1, key, 60, Problem.TMDB_KEY)
    problems.waiting(2, key, 60, Problem.TMDB_KEY)
    problems.waiting(3, "The NAS isn't connected", 60)

    [banner] = problems.banners()
    assert banner.problem == Problem.TMDB_KEY and banner.jobs == 2

    problems.moved_on(1)
    assert [b.jobs for b in problems.banners()] == [1]
    problems.moved_on(2)
    assert problems.banners() == []


def _rip(h, label="EXAMPLE_MOVIE", disc_type=DiscType.BD) -> None:
    h.makemkv.release()
    h.drive.insert(disc_type, label)
    eventually(lambda: h.drive.ejected >= 1)


def _now(c) -> str:
    return html.unescape(c.get("/").text)


def test_with_no_tmdb_key_a_ripped_video_disc_shows_a_banner_and_why_its_card_waits(tmp_path):
    h = make_harness(tmp_path, tmdb_key="")
    h.web.add_film("Example Movie", 1234, "Example Movie", runtime=122)
    with TestClient(create_app(h.services)) as c:
        _rip(h)
        eventually(lambda: "[tmdb] api_key" in _now(c))
        page = _now(c)
        assert 'sse-swap="problems"' in page
        banner = page[page.index('sse-swap="problems"'):page.index('class="split"')]
        assert "No TMDB API key" in banner and "[tmdb] api_key" in banner
        ripping = page[page.index('id="ripping-h"'):page.index('id="encoding-h"')]
        assert "Waiting: No TMDB API key is set in ama.toml ([tmdb] api_key)" in ripping
        assert "next try" in ripping
        disc_page = html.unescape(c.get("/discs/1").text)
        assert "Waiting: No TMDB API key" in disc_page

        h.services.tmdb._key = "tmdb-key"  # the key is set (Settings, #26)
        eventually(lambda: h.services.discs.list(DiscStatus.FILED), timeout=5)
        page = _now(c)
        assert "[tmdb] api_key" not in page and "Waiting:" not in page
        assert "Waiting:" not in html.unescape(c.get("/discs/1/waiting").text)


def test_the_banner_and_waiting_line_come_and_go_over_sse_without_a_reload(tmp_path):
    h = make_harness(tmp_path, tmdb_key="")
    h.web.add_film("Example Movie", 1234, "Example Movie", runtime=122)
    server = uvicorn.Server(uvicorn.Config(create_app(h.services), host="127.0.0.1", port=0,
                                           log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    try:
        eventually(lambda: server.started)
        port = server.servers[0].sockets[0].getsockname()[1]
        with httpx.stream("GET", f"http://127.0.0.1:{port}/events", timeout=10) as r:
            lines = r.iter_lines()
            assert "[tmdb] api_key" not in _read_event(lines, "problems")  # on connect
            _rip(h)
            while "[tmdb] api_key" not in _read_event(lines, "problems"):
                pass
            while "Waiting: No TMDB API key" not in _read_event(lines, "ripping"):
                pass
            h.services.tmdb._key = "tmdb-key"
            while "[tmdb] api_key" in _read_event(lines, "problems"):
                pass
            while "Waiting:" in _read_event(lines, "ripping"):
                pass
    finally:
        server.should_exit = True
        t.join(5)


def test_a_job_waiting_for_the_nas_says_so_until_the_nas_is_back(tmp_path):
    h = make_harness(tmp_path, nas_reachable=False)
    h.web.add_film("Example Movie", 1234, "Example Movie", runtime=122)
    with TestClient(create_app(h.services)) as c:
        _rip(h)
        eventually(lambda: "Waiting: The NAS isn't connected" in _now(c))
        encoding = _now(c)[_now(c).index('id="encoding-h"'):]
        assert "Waiting: The NAS isn't connected" in encoding  # Encoded, waiting to file
        assert "Can't reach the NAS" in _now(c)  # the app-wide NAS banner
        h.share["reachable"] = True
        eventually(lambda: h.services.discs.list(DiscStatus.FILED), timeout=5)
        eventually(lambda: "Waiting:" not in _now(c))


def test_a_job_queued_behind_another_encode_is_not_shown_as_a_problem(client, harness):
    harness.ffmpeg.hold = True
    harness.web.add_film("Example Movie", 1234, "Example Movie", runtime=122)
    harness.web.add_film("Other Movie", 99, "Other Movie", runtime=122, year=2001)
    _rip(harness)
    eventually(harness.ffmpeg.encoding.is_set)
    harness.makemkv.disc_name = "Other Movie"
    harness.drive.insert(DiscType.BD, "OTHER_MOVIE")
    eventually(lambda: harness.drive.ejected == 2)
    eventually(lambda: harness.services.movie_archive.movies.get(2) is not None)
    time.sleep(0.3)  # several Encode passes go by
    page = _now(client)
    assert "Next in line" in page
    assert "Waiting:" not in page and harness.services.problems.why(2) is None
    assert harness.services.problems.banners() == []
    harness.ffmpeg.release()


def test_a_failing_plex_scan_shows_a_banner_until_a_scan_works(tmp_path):
    status = {"code": 401}
    web = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(
        status["code"], json={"MediaContainer": {"Directory": [
            {"key": "1", "Location": [{"path": "/media/Movies"}]}]}})))
    problems = Problems(EventBus(), now=lambda: NOW)
    plex = Plex(PlexConfig(url="http://plex:32400", token="t", nas_path="/media"), web,
                tmp_path, problems)
    with pytest.raises(httpx.HTTPError):
        plex.scan(tmp_path / "Movies" / "Film")
    [banner] = problems.banners()
    assert banner.problem == Problem.PLEX and banner.detail == "HTTP 401"
    assert "t" not in banner.detail.split()  # no token, no URL

    status["code"] = 200
    plex.scan(tmp_path / "Movies" / "Film")
    assert problems.banners() == []


def test_a_failing_notification_shows_a_banner_until_one_gets_through(harness):
    class Channel:
        name = "Discord"
        fail = True

        def send(self, note):
            if self.fail:
                raise OSError("no network")

    problems = Problems(EventBus(), now=lambda: NOW)
    ch = Channel()
    notifier = Notifier(harness.services.discs, EventBus(), [ch], problems)
    note = Notification(next(iter(Event)), "Disc done", "Insert the next one")
    notifier.send([note])
    [banner] = problems.banners()
    assert banner.problem == Problem.NOTIFY and banner.detail == "Discord: OSError"

    ch.fail = False
    notifier.send([note])
    assert problems.banners() == []


def test_the_now_page_words_each_reported_problem_with_its_fix(client, harness):
    harness.services.problems.report(Problem.PLEX, "HTTP 401")
    harness.services.problems.report(Problem.NOTIFY, "Discord: HTTP 404")
    page = _now(client)
    assert "Plex didn't answer" in page and "[plex] url" in page and "HTTP 401" in page
    assert "Couldn't send the last notification" in page and "[discord] webhook_url" in page
    harness.services.problems.resolved(Problem.PLEX)
    harness.services.problems.resolved(Problem.NOTIFY)
    page = _now(client)
    assert "Plex didn't answer" not in page and "Couldn't send the last" not in page


def test_a_reported_app_wide_problem_shows_until_it_is_resolved():
    bus = EventBus()
    problems = Problems(bus, now=lambda: NOW)
    seen = _published(bus, lambda: problems.report(Problem.PLEX, "HTTP 401"))
    assert Topic.PROBLEMS in seen
    [banner] = problems.banners()
    assert banner.problem == Problem.PLEX and banner.detail == "HTTP 401"

    problems.resolved(Problem.PLEX)
    assert problems.banners() == []
