import httpx

from ama.drive import DiscType, UnrecognisedDisc
from tests.conftest import eventually


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


def test_ama_never_connects_storage_and_now_has_no_nas_panel(client, harness):
    eventually(lambda: any(r.title == "AMA started" and r.finished_at
                           for r in harness.services.runs.list_runs()))
    assert harness.runner.calls == []
    assert "NAS" not in client.get("/").text


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

        # The Rip that just started may have pushed updates rendered before the eject.
        harness.drive.eject()
        while "Insert a Disc" not in _read_event(lines, "drive"):
            pass
