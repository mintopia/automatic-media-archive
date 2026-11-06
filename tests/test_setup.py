"""Setup (ADR 0016): with no settings file, a localhost wizard writes one."""

from __future__ import annotations

import html
import threading
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from ama.config import LibraryKind, load_config
from ama.setup import Setup, create_setup_app, run_setup
from ama.web.auth import CONTROL_HEADER
from tests.conftest import eventually


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    """The user's home, where the default Libraries live."""
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


@pytest.fixture
def setup(tmp_path, home) -> Setup:
    return Setup(tmp_path / "AMA" / "ama.toml")


@pytest.fixture
def client(setup) -> TestClient:
    return TestClient(create_setup_app(setup))


def _walk(client: TestClient) -> list[str]:
    """Follow Setup from the start, continuing with what's prefilled; the pages' titles."""
    titles = []
    r = client.get("/")
    while r.request.url.path != "/setup/ready":
        titles.append(r.text.split("<h1>", 1)[1].split("</h1>", 1)[0])
        r = client.post(r.request.url.path, data=_prefilled(r.text))
        assert r.status_code == 200, r.text
    return titles


def _prefilled(html: str) -> dict[str, str]:
    """The form's inputs with the values the page filled in."""
    import re
    return {m["name"]: m["value"] for m in re.finditer(
        r'<input[^>]*name="(?P<name>[^"]+)"[^>]*value="(?P<value>[^"]*)"', html)}


def test_setup_goes_welcome_then_where_things_go_then_ready(client):
    assert _walk(client) == ["Welcome to AMA", "Where things go"]
    assert "<h1>Ready</h1>" in client.get("/setup/ready").text


def test_where_things_go_is_prefilled_with_the_default_libraries_and_scratch(client, setup, home):
    page = client.get("/setup/where").text
    values = _prefilled(page)
    assert values["films"] == str(home / "Videos" / "Movies")
    assert values["tv"] == str(home / "Videos" / "TV")
    assert values["music"] == str(home / "Music")
    assert values["scratch"] == str(setup.config.parent / "Scratch")
    advanced = page.split("<details", 1)[1]  # Scratch sits under Advanced, closed
    assert "Advanced" in advanced and 'name="scratch"' in advanced
    assert "<details open" not in page


def test_finishing_writes_the_settings_file_with_the_choices_and_defaults(client, setup, tmp_path):
    _walk(client)
    films = tmp_path / "nas" / "Films"
    client.post("/setup/where", data={"films": str(films), "tv": str(tmp_path / "TV"),
                                      "music": str(tmp_path / "Music"),
                                      "scratch": str(tmp_path / "scratch")})
    r = client.post("/setup/ready")
    assert r.status_code == 200 and "Starting AMA" in r.text
    assert setup.finished.is_set()
    cfg = load_config(setup.config)
    films_lib = next(lib for lib in cfg.libraries if lib.kind == LibraryKind.FILMS)
    assert (films_lib.path, films_lib.default) == (str(films), True)
    assert cfg.paths.scratch == tmp_path / "scratch"
    assert cfg.web.host == "0.0.0.0"  # not asked yet: the default
    assert (cfg.encode.cq.dvd, cfg.encode.cq.bd, cfg.encode.cq.uhd) == (20, 22, 22)


def test_finishing_without_changing_anything_takes_every_default(client, setup, home):
    _walk(client)
    client.post("/setup/ready")
    cfg = load_config(setup.config)
    assert {lib.kind: Path(lib.path) for lib in cfg.libraries} == {
        k: k.default_path() for k in LibraryKind}
    assert cfg.paths.scratch == setup.config.parent / "Scratch"


@pytest.mark.parametrize("field", ["films", "scratch"])
def test_a_path_that_isnt_writable_is_named_and_setup_stays_on_the_step(client, setup, tmp_path,
                                                                        field):
    blocker = tmp_path / "a-file"
    blocker.write_text("not a folder", encoding="utf-8")
    form = _prefilled(client.get("/setup/where").text) | {field: str(blocker / "inside")}
    r = client.post("/setup/where", data=form)
    assert r.request.url.path == "/setup/where" and r.status_code == 422
    assert "can't write" in html.unescape(r.text) and 'aria-invalid="true"' in r.text
    client.post("/setup/ready")
    assert not setup.config.exists() and not setup.finished.is_set()


def test_a_relative_path_is_refused(client):
    form = _prefilled(client.get("/setup/where").text) | {"tv": "TV"}
    r = client.post("/setup/where", data=form)
    assert r.status_code == 422 and "full folder path" in r.text


def test_setup_serves_nothing_but_setup(client):
    for path in ("/settings", "/history", "/review"):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/setup/welcome"


def test_setup_cant_be_run_again_once_the_file_exists(client, setup):
    _walk(client)
    client.post("/setup/ready")
    before = setup.config.read_bytes()
    r = client.post("/setup/ready")
    assert r.status_code == 409
    assert setup.config.read_bytes() == before


def test_a_file_written_by_hand_meanwhile_is_kept(client, setup):
    setup.config.parent.mkdir(parents=True)
    setup.config.write_text("[paths]\nscratch = 'mine'\n", encoding="utf-8")
    r = client.post("/setup/ready")
    assert r.status_code == 409
    assert setup.config.read_text(encoding="utf-8") == "[paths]\nscratch = 'mine'\n"
    assert setup.finished.is_set()  # AMA starts with the hand-written file


def test_the_finished_page_waits_for_the_real_server(client, setup):
    _walk(client)
    page = client.post("/setup/ready").text
    assert 'data-boot-url="/boot"' in page and f'data-boot="{setup.boot}"' in page
    assert client.get("/boot").json() == {"boot": setup.boot}


def test_the_trays_quit_stops_setup_and_nothing_else_can(setup):
    quits: list[bool] = []
    app = create_setup_app(setup, control_token="tok")
    app.state.on_quit = lambda: quits.append(True)
    client = TestClient(app)
    assert client.post("/control/quit").status_code == 403
    assert client.post("/control/quit", headers={CONTROL_HEADER: "tok"}).status_code == 204
    assert quits == [True]


def _start(setup: Setup, **kw) -> tuple[threading.Thread, list[str], list[bool]]:
    """`run_setup` on a free port in a thread; (thread, URLs it opened, what it returned)."""
    opened: list[str] = []
    result: list[bool] = []
    t = threading.Thread(target=lambda: result.append(
        run_setup(setup.config, port=0, open_url=opened.append, **kw)))
    t.start()
    eventually(lambda: opened)
    return t, opened, result


def test_setup_listens_on_localhost_only_and_hands_over_once_the_file_is_written(setup):
    t, opened, result = _start(setup)
    [url] = opened
    assert url.startswith("http://127.0.0.1:")
    with httpx.Client(base_url=url, follow_redirects=True) as http:
        assert "Welcome to AMA" in http.get("/").text
        http.post("/setup/ready")
    t.join(10)
    assert result == [True] and setup.config.exists()


def test_quitting_setup_hands_over_nothing(setup):
    t, opened, result = _start(setup, control_token="tok")
    httpx.post(opened[0] + "control/quit", headers={CONTROL_HEADER: "tok"})
    t.join(10)
    assert result == [False] and not setup.config.exists()


def test_a_missing_settings_file_starts_setup_instead_of_an_error(tmp_path, monkeypatch):
    import ama.__main__ as main
    started: list[Path] = []
    monkeypatch.setattr(main, "run_setup", lambda config, **kw: started.append(config) or False)
    monkeypatch.setattr(main, "_setup_logging", lambda log_file: None)
    config = tmp_path / "AMA" / "ama.toml"
    main.serve(config)  # Setup stopped before finishing: no error, nothing more
    assert started == [config]


def test_an_existing_settings_file_never_starts_setup(tmp_path, monkeypatch):
    import ama.__main__ as main
    monkeypatch.setattr(main, "run_setup", lambda config, **kw: pytest.fail("ran Setup"))
    config = tmp_path / "ama.toml"
    config.write_text("[web]\nport = 'eighty'\n", encoding="utf-8")  # even a broken one
    with pytest.raises(SystemExit):
        main.serve(config)
