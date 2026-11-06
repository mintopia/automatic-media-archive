"""Screenshots of the real app for the website: uv run python docs/mockups/tools/app_screenshots.py

Runs AMA with the test fakes (tests/conftest.py) in a throwaway folder, never your own
settings or History, and feeds it the example Discs: Queen's Greatest Hits and Firefly
Disc 1 filed, Ocean's Thirteen answered in Review and filed, Ocean's Twelve encoding,
Firefly Disc 2 waiting in Review and Ocean's Eleven ripping. Then headless Chrome
(capture.mjs) shoots Now, both Reviews and History into website/public/screenshots/.
Posters, the cover and the Title stills are plain generated pictures.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402
import uvicorn  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from ama.app import create_app  # noqa: E402
from ama.drive import DiscType  # noqa: E402
from ama.jobs import JobStatus, TitleRecord, TitleStatus  # noqa: E402
from tests import fakes  # noqa: E402
from tests.conftest import eventually, make_harness  # noqa: E402

OUT = ROOT / "website" / "public" / "screenshots"
DESKTOP = {"width": 1440, "height": 850, "mobile": False, "fullPage": False}
MOBILE = {"width": 390, "height": 844, "mobile": True, "fullPage": False}

QUEEN_DISC = "x8Hn7HbFq0e2sEAp0v6qQ3S2xDg-"
QUEEN_RELEASE = "4a1f4c0e-5e2b-4f5e-9d47-5c1a3b8d9f01"
QUEEN_TRACKS = [
    ("Bohemian Rhapsody", 355), ("Another One Bites the Dust", 215), ("Killer Queen", 177),
    ("Fat Bottomed Girls", 202), ("Bicycle Race", 181), ("You're My Best Friend", 171),
    ("Don't Stop Me Now", 209), ("Save Me", 228), ("Crazy Little Thing Called Love", 162),
    ("Somebody to Love", 296), ("Now I'm Here", 254), ("Good Old-Fashioned Lover Boy", 174),
    ("Play the Game", 210), ("Flash", 168), ("Seven Seas of Rhye", 167),
    ("We Will Rock You", 121), ("We Are the Champions", 179)]

FIREFLY = 1437
FIREFLY_SEASON_1 = [(1, "Serenity", 86), (2, "The Train Job", 44), (3, "Bushwhacked", 44),
                    (4, "Shindig", 44), (5, "Safe", 44), (6, "Our Mrs. Reynolds", 44),
                    (7, "Jaynestown", 44), (8, "Out of Gas", 44), (9, "Ariel", 44),
                    (10, "War Stories", 44), (11, "Trash", 44), (12, "The Message", 44),
                    (13, "Heart of Gold", 44), (14, "Objects in Space", 44)]

# The Main Feature's length on the next Blu-ray (the fake scan's is 2:01:33).
main_feature = {"length": "2:01:33"}
_lines = fakes._lines


def _scan_lines(name: str) -> list[str]:
    return [ln.replace('"2:01:33"', f'"{main_feature["length"]}"') for ln in _lines(name)]


def picture(width: int, height: int, top: str, bottom: str) -> bytes:
    """A plain two-colour gradient, as a JPEG."""
    img = Image.new("RGB", (width, height))
    a, b = Image.new("RGB", (1, 1), top).getpixel((0, 0)), Image.new("RGB", (1, 1), bottom).getpixel((0, 0))
    draw = ImageDraw.Draw(img)
    for y in range(height):
        t = y / max(height - 1, 1)
        draw.line([(0, y), (width, y)], fill=tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3)))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=85)
    return out.getvalue()


STILLS = [("#1d2b3a", "#c08a3e"), ("#2a1f2e", "#6c8ea0"), ("#11262a", "#d4b483"),
          ("#3a2a1c", "#8aa39b"), ("#1f2333", "#b5654a"), ("#2e3a25", "#cfc6a8")]


def _real_stills(ffmpeg: fakes.FakeFfmpeg) -> None:
    """The fake ffmpeg's Review stills, as pictures a browser shows."""
    call = type(ffmpeg).__call__

    def stills(self, args, on_line, cwd=None):
        code = call(self, args, on_line, cwd)
        if "-frames:v" in args and str(args[-1]).endswith(".jpg") and code == 0:
            top, bottom = STILLS[len(self.thumbnails) % len(STILLS)]
            Path(args[-1]).write_bytes(picture(320, 180, top, bottom))
        return code
    type(ffmpeg).__call__ = stills


def _queen(harness) -> None:
    offsets, at = [], 150
    for _, secs in QUEEN_TRACKS:
        offsets.append(at)
        at += secs * 75
    credit = [{"name": "Queen", "joinphrase": "", "artist": {
        "id": "0383dadf-2a4e-4d10-a46a-e9e041da8eb3", "name": "Queen", "sort-name": "Queen",
        "type": "Group", "disambiguation": ""}}]
    tracks = [{"id": f"t{n}", "number": str(n), "position": n, "title": title,
               "length": secs * 1000, "artist-credit": credit,
               "recording": {"id": f"r{n}", "title": title, "length": secs * 1000,
                             "artist-credit": credit, "video": False, "disambiguation": ""}}
              for n, (title, secs) in enumerate(QUEEN_TRACKS, 1)]
    disc = {"id": QUEEN_DISC, "sectors": at, "offsets": offsets, "offset-count": len(offsets)}
    release = {"id": QUEEN_RELEASE, "title": "Greatest Hits", "status": "Official",
               "date": "1981-10-26", "country": "GB", "barcode": "077774602221",
               "artist-credit": credit, "disambiguation": "", "quality": "normal",
               "release-group": {"id": "2b9f6e33-7b0c-4c3a-9b6f-0d5a1c8f4e21"},
               "label-info": [{"catalog-number": "EMTV 30", "label": {"name": "EMI"}}],
               "cover-art-archive": {"front": True, "artwork": True, "count": 1},
               "media": [{"position": 1, "format": "CD", "title": "", "track-offset": 0,
                          "track-count": len(tracks), "discs": [disc], "tracks": tracks}]}
    harness.web.musicbrainz[QUEEN_DISC] = {"id": QUEEN_DISC, "sectors": at, "offsets": offsets,
                                          "offset-count": len(offsets), "releases": [release]}
    harness.web.covers[QUEEN_RELEASE] = picture(500, 500, "#7a1f2b", "#e0b04a")
    harness.cyanrip.mb_disc_id = QUEEN_DISC
    harness.cyanrip.tracks = [(n, float(secs)) for n, (_, secs) in enumerate(QUEEN_TRACKS, 1)]
    harness.cyanrip.ar_confidence = {n: 200 for n in range(1, len(QUEEN_TRACKS) + 1)}


def _films(harness) -> None:
    web = harness.web
    films = [("Ocean's Twelve", 163, "Ocean's Twelve", 125, 2004, "Steven Soderbergh"),
             ("OCEANS", 161, "Ocean's Eleven", 116, 2001, "Steven Soderbergh"),
             ("OCEANS", 163, "Ocean's Twelve", 125, 2004, "Steven Soderbergh"),
             ("OCEANS", 298, "Ocean's Thirteen", 122, 2007, "Steven Soderbergh"),
             ("Ocean's Eleven", 161, "Ocean's Eleven", 116, 2001, "Steven Soderbergh"),
             ("OCEANS ELEVEN", 161, "Ocean's Eleven", 116, 2001, "Steven Soderbergh")]
    colours = {161: ("#0f2a3d", "#d9a441"), 163: ("#2b1838", "#e07a3f"),
               298: ("#13312a", "#c9b26b")}
    for query, id_, title, runtime, year, director in films:
        web.add_film(query, id_, title, runtime, year=year, director=director,
                     poster_path=f"/poster{id_}.jpg")
        web.tmdb_images[f"/poster{id_}.jpg"] = picture(342, 513, *colours[id_])


def _firefly(harness) -> None:
    harness.web.add_series("FIREFLY", FIREFLY, "Firefly", 2002, {
        1: FIREFLY_SEASON_1, 0: [(1, "Here's How It Was: The Making of Firefly", 29)]},
        poster_path="/firefly.jpg")
    harness.web.tmdb_images["/firefly.jpg"] = picture(342, 513, "#2b1a12", "#c4632f")


def _tv_disc(harness, label: str, titles: list[tuple[int, int, str]]):
    """A TV DVD put into Scratch as ripped (the fake makemkvcon only knows a film's Blu-ray)."""
    jobs = harness.services.jobs
    rec = jobs.create(DiscType.DVD, label, "video")
    rec.scratch_dir.mkdir(parents=True)
    records = []
    for n, seconds, segments in titles:
        name = f"{label}_t{n - 1:02d}.mkv"
        (rec.scratch_dir / name).write_bytes(b"mkv")
        records.append(TitleRecord(n, n - 1, seconds, 1_000_000_000, 2, 1, segments, name,
                                   TitleStatus.RIPPED))
    jobs.set_titles(rec.id, records, 0, 0)
    jobs.mark_ripped(rec.id)
    eventually(lambda: jobs.get(rec.id).status == JobStatus.REVIEW, timeout=10)
    return rec


def _bluray(harness, label: str, name: str, length: str) -> None:
    """A Blu-ray whose volume `label` and MakeMKV Disc `name` are these, with the Main
    Feature `length` long."""
    main_feature["length"] = length
    harness.makemkv.disc_name = name
    harness.makemkv.title_names = {0: name, 1: name, 2: name, 3: name}
    harness.drive.insert(DiscType.BD, label)


def _status(harness, label: str, status: JobStatus):
    return next((j for j in harness.services.jobs.list(status) if j.label == label), None)


def _stills_of(harness, name: str, count: int) -> None:
    """Wait for `count` Review stills of the Rip files whose names contain `name`."""
    eventually(lambda: sum(name in str(c) for c in harness.ffmpeg.thumbnails) >= count, timeout=30)


def _serve(app) -> tuple[uvicorn.Server, str]:
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    eventually(lambda: server.started)
    return server, f"http://127.0.0.1:{server.servers[0].sockets[0].getsockname()[1]}"


def main() -> None:
    fakes._lines = _scan_lines
    with tempfile.TemporaryDirectory(prefix="ama-shots-", ignore_cleanup_errors=True) as tmp:
        harness = make_harness(Path(tmp))
        harness.disk.used = 108 * 1000**3
        _real_stills(harness.ffmpeg)
        _queen(harness)
        _films(harness)
        _firefly(harness)
        server, url = _serve(create_app(harness.services))
        web = httpx.Client(base_url=url, follow_redirects=False, timeout=30)
        jobs = harness.services.jobs
        try:
            # Queen, Greatest Hits: ripped, verified by AccurateRip, filed.
            harness.drive.insert(DiscType.CD, "")
            eventually(lambda: jobs.list(JobStatus.FILED), timeout=30)
            harness.drive.eject()

            # Firefly Disc 1: TV always goes to Review; the Episodes are answered, then filed.
            disc1 = _tv_disc(harness, "FIREFLY_D1", [(1, 86 * 60 + 12, "1"), (2, 44 * 60 + 5, "2"),
                                                     (3, 43 * 60 + 51, "3"), (4, 44 * 60 + 20, "4"),
                                                     (5, 4 * 60 + 2, "9")])
            r = web.post(f"/review/{disc1.id}/episodes", data={
                "series": str(FIREFLY), "season": "1", "t1": "S01E01", "t2": "S01E02",
                "t3": "S01E03", "t4": "S01E04", "t5": "discard"})
            assert r.status_code == 303, r.text
            eventually(lambda: jobs.get(disc1.id).status == JobStatus.FILED, timeout=30)

            # Ocean's Thirteen, labelled just "OCEANS": Twelve and Thirteen both fit its
            # length, so AMA asks which it is.
            harness.makemkv.release()
            _bluray(harness, "OCEANS", "Oceans", "2:02:10")
            eventually(lambda: _status(harness, "OCEANS", JobStatus.REVIEW), timeout=30)
            thirteen = _status(harness, "OCEANS", JobStatus.REVIEW)
            _stills_of(harness, "Example_Movie", 6)
            shots = [("review-film", f"{url}/review/{thirteen.id}", [DESKTOP])]
            _capture(shots)
            r = web.post(f"/review/{thirteen.id}/film", data={"film": "298", "title": "1"})
            assert r.status_code == 303, r.text
            eventually(lambda: jobs.get(thirteen.id).status == JobStatus.FILED, timeout=30)

            # Ocean's Twelve: a confident match, held mid-Encode.
            harness.ffmpeg.hold = True
            _bluray(harness, "OCEANS_TWELVE", "Ocean's Twelve", "2:05:12")
            eventually(harness.ffmpeg.encoding.is_set, timeout=30)

            # Firefly Disc 2: Disc 2 of the set Disc 1 started, waiting for its Episodes.
            disc2 = _tv_disc(harness, "FIREFLY_D2", [(1, 44 * 60 + 2, "1"), (2, 43 * 60 + 40, "2"),
                                                     (3, 44 * 60 + 11, "3"), (4, 43 * 60 + 58, "4")])
            r = web.post(f"/review/{disc2.id}/set",
                         data={"part": "yes", "set": f"tv:{FIREFLY}:1", "disc": "2"})
            assert r.status_code == 303, r.text

            # Ocean's Eleven: held mid-Rip.
            harness.makemkv._go.clear()
            _bluray(harness, "OCEANS_ELEVEN", "Ocean's Eleven", "1:56:24")
            eventually(lambda: harness.makemkv.ripping, timeout=30)
            _stills_of(harness, "FIREFLY_D2", 12)

            _capture([("now", f"{url}/", [DESKTOP, MOBILE]),
                      ("review-tv", f"{url}/review/{disc2.id}", [DESKTOP]),
                      ("history", f"{url}/history", [DESKTOP])])
        except AssertionError:
            for n in range(1, 10):
                if rec := jobs.get(n):
                    print(rec.id, rec.label, rec.status, *map(str, jobs.log_lines(n)[-4:]), sep="\n  ")
            raise
        finally:
            harness.makemkv.release()
            harness.ffmpeg.release()
            server.should_exit = True


def _capture(shots: list[tuple[str, str, list[dict]]]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    spec = [{**view, "url": url, "theme": theme,
             "out": str(OUT / f"{name}-{'mobile' if view['mobile'] else 'desktop'}-{theme}.png")}
            for name, url, views in shots for view in views for theme in ("light", "dark")]
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(spec, f)
    try:
        subprocess.run(["node", str(Path(__file__).with_name("capture.mjs")), f.name], check=True)
    finally:
        Path(f.name).unlink()


if __name__ == "__main__":
    main()
