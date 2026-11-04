import httpx
from fastapi.testclient import TestClient

from ama.app import create_app
from ama.drive import DiscType, UnrecognisedDisc
from tests.conftest import eventually, make_harness


def test_empty_drive_asks_for_a_disc(client):
    page = client.get("/").text
    assert "Drive empty" in page and "Insert a Disc" in page


def test_disc_in_the_drive_shows_its_disc_type_and_label(client, harness):
    harness.drive.insert(DiscType.UHD, "BLADE_RUNNER_2049")
    eventually(lambda: "BLADE_RUNNER_2049" in client.get("/").text)
    page = client.get("/").text
    assert "<span>UHD Blu-ray</span>" in page and "Insert a Disc" not in page


def test_unrecognised_disc_says_so_plainly(client, harness):
    harness.drive.state = UnrecognisedDisc("BACKUP_2019")
    eventually(lambda: "BACKUP_2019" in client.get("/").text)
    assert "can't archive this Disc" in client.get("/").text


def test_nas_failure_is_shown_and_clears_when_the_share_comes_back(tmp_path):
    h = make_harness(tmp_path, nas_reachable=False)
    with TestClient(create_app(h.services)) as client:
        eventually(lambda: "Can't reach the NAS" in client.get("/").text)
        page = client.get("/").text
        assert r"\\nas\media" in page and "The network path was not found." in page
        assert h.runner.calls[0][:3] == ["net", "use", r"\\nas\media"]
        h.share["reachable"] = True
        eventually(lambda: "Can't reach the NAS" not in client.get("/").text)


def test_static_assets_are_served(client):
    assert client.get("/static/ama.css").status_code == 200
    assert client.get("/static/vendor/htmx.min.js").status_code == 200


def _read_event(lines, name: str) -> str:
    """Return the data of the next SSE event called `name`."""
    event, data = None, []
    for line in lines:
        if line.startswith("event: "):
            event = line[7:]
        elif line.startswith("data: "):
            data.append(line[6:])
        elif line == "":
            if event == name:
                return "\n".join(data)
            event, data = None, []
    raise AssertionError(f"stream ended before a {name!r} event")


def test_inserting_and_removing_a_disc_is_pushed_live_over_sse(live_server, harness):
    with httpx.stream("GET", f"{live_server}/events", timeout=5) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        lines = r.iter_lines()
        assert "Insert a Disc" in _read_event(lines, "drive")  # sent on connect

        harness.drive.insert(DiscType.DVD, "HEAT_DISC1")
        fragment = _read_event(lines, "drive")
        assert "DVD" in fragment and "HEAT_DISC1" in fragment

        harness.drive.eject()
        assert "Insert a Disc" in _read_event(lines, "drive")
