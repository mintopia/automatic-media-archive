"""Update available (https://git.mintopia.net/mintopia/automatic-media-archive/issues/77):
AMA asks GitHub Releases for a newer vX.Y.Z, at most daily, and never updates itself
(ADR 0017). Every test answers over an httpx MockTransport; none reaches GitHub."""

import httpx
from fastapi.testclient import TestClient

from ama.app import create_app
from ama.db import Database
from ama.events import EventBus
from ama.updates import UpdateCheck
from tests.conftest import eventually

RELEASES = "https://github.com/mintopia/automatic-media-archive/releases/tag/"


def release(tag: str, prerelease: bool = False, draft: bool = False) -> dict:
    return {"tag_name": tag, "html_url": RELEASES + tag, "prerelease": prerelease,
            "draft": draft}


class FakeGitHub:
    def __init__(self, releases: list[dict]) -> None:
        self.releases = releases
        self.offline = False
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.offline:
            raise httpx.ConnectError("no network", request=request)
        assert request.url.host == "api.github.com"
        assert request.url.path == "/repos/mintopia/automatic-media-archive/releases"
        return httpx.Response(200, json=self.releases)


class Clock:
    def __init__(self) -> None:
        self.t = 1_800_000_000.0

    def __call__(self) -> float:
        return self.t


def checker(tmp_path, github: FakeGitHub, clock: Clock, running: str = "0.1.0") -> UpdateCheck:
    return UpdateCheck(httpx.Client(transport=httpx.MockTransport(github.handle)),
                       Database(tmp_path / "state.db"), EventBus(), running=running, now=clock)


def test_a_newer_release_is_available_with_its_link(tmp_path):
    github = FakeGitHub([release("v0.1.0"), release("v0.2.0"), release("v0.1.1")])
    check = checker(tmp_path, github, Clock())
    check.check()
    assert check.available is not None
    assert check.available.tag == "v0.2.0"
    assert check.available.url == RELEASES + "v0.2.0"


def test_cyanrip_builds_pre_releases_and_drafts_are_never_updates(tmp_path):
    github = FakeGitHub([release("cyanrip-0.9.3"), release("cyanrip-1.0.0"),
                         release("v0.3.0", prerelease=True), release("v0.4.0", draft=True),
                         release("v0.3.0-rc1"), release("v0.1.0")])
    check = checker(tmp_path, github, Clock())
    check.check()
    assert check.available is None


def test_nothing_is_available_when_running_the_newest(tmp_path):
    github = FakeGitHub([release("v0.1.0"), release("v0.0.9")])
    check = checker(tmp_path, github, Clock())
    check.check()
    assert check.available is None
    # versions compare as numbers, not text
    check = checker(tmp_path / "b", FakeGitHub([release("v0.10.0")]), Clock(), running="0.9.0")
    check.check()
    assert check.available.tag == "v0.10.0"


def test_network_failures_are_silent(tmp_path):
    github = FakeGitHub([release("v0.2.0")])
    github.offline = True
    check = checker(tmp_path, github, Clock())
    check.check()  # raises nothing
    assert check.available is None


def test_github_errors_and_junk_are_silent(tmp_path):
    for answer in (httpx.Response(403, json={"message": "rate limited"}),
                   httpx.Response(200, content=b"<html>"),
                   httpx.Response(200, json={"not": "a list"}),
                   httpx.Response(200, json=[{"tag_name": 7}])):
        (tmp_path / "x").mkdir(exist_ok=True)
        check = UpdateCheck(httpx.Client(transport=httpx.MockTransport(lambda r, a=answer: a)),
                            Database(tmp_path / "x" / f"{id(answer)}.db"), EventBus(),
                            running="0.1.0", now=Clock())
        check.check()
        assert check.available is None


def test_checks_at_most_daily_even_across_restarts(tmp_path):
    github = FakeGitHub([release("v0.1.0")])
    clock = Clock()
    checker(tmp_path, github, clock).check()
    assert len(github.requests) == 1
    github.releases.append(release("v0.2.0"))
    clock.t += 23 * 3600
    restarted = checker(tmp_path, github, clock)
    restarted.check()
    assert len(github.requests) == 1 and restarted.available is None
    clock.t += 3600
    restarted.check()
    assert len(github.requests) == 2 and restarted.available.tag == "v0.2.0"


def test_a_failed_check_also_waits_a_day(tmp_path):
    github = FakeGitHub([release("v0.2.0")])
    github.offline = True
    clock = Clock()
    check = checker(tmp_path, github, clock)
    check.check()
    github.offline = False
    clock.t += 3600
    check.check()
    assert len(github.requests) == 1 and check.available is None


def test_a_found_update_survives_a_restart_and_goes_once_installed(tmp_path):
    github = FakeGitHub([release("v0.2.0")])
    clock = Clock()
    checker(tmp_path, github, clock).check()
    clock.t += 3600
    assert checker(tmp_path, github, clock).available.tag == "v0.2.0"
    assert checker(tmp_path, github, clock, running="0.2.0").available is None
    assert len(github.requests) == 1


def test_now_and_the_menu_show_the_update_with_a_link_to_the_release(harness):
    harness.web.github_releases = [release("cyanrip-2.0.0"), release("v1000.0.0", prerelease=True),
                                   release("v0.1.0"), release("v999.0.0")]
    with TestClient(create_app(harness.services)) as client:
        eventually(lambda: "Update available" in client.get("/").text)
        now = client.get("/").text
        assert f'href="{RELEASES}v999.0.0"' in now and "v999.0.0" in now
        assert "cyanrip" not in now and "v1000.0.0" not in now
        history = client.get("/history").text  # every page: the top-bar menu
        assert "Update available" in history and f'href="{RELEASES}v999.0.0"' in history


def test_no_notice_while_github_is_unreachable(harness):
    harness.web.github_offline = True
    with TestClient(create_app(harness.services)) as client:
        eventually(lambda: harness.services.updates.due_in() > 0)
        assert "Update available" not in client.get("/").text
        assert not harness.services.problems.banners()
