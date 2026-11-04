"""Fakes for the hardware/OS/process boundary. Tests never touch real devices."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Sequence
from pathlib import Path

import httpx

from ama.drive import DiscPresent, DiscType, DriveEmpty, DriveState, UnrecognisedDisc
from ama.proc import ProcResult
from ama.scratch import DiskUsage


class FakeDrive:
    """A `DriveProbe` whose contents the test controls."""

    def __init__(self) -> None:
        self.state: DriveState = DriveEmpty()
        self._error: Exception | None = None
        self.ejected = 0
        self.stuck = False  # eject() fails and the Disc stays in
        self.root: Path | None = None  # the Disc's filesystem (e.g. BDMV/META), if a test makes one

    def insert(self, disc_type: DiscType, label: str = "") -> None:
        self.state = DiscPresent(disc_type, label)

    def insert_unrecognised(self, label: str = "") -> None:
        self.state = UnrecognisedDisc(label)

    def eject(self) -> None:
        """The tray opens (from the app, or by hand): the drive is empty."""
        if self.stuck:
            raise OSError("The tray is stuck")
        self.ejected += 1
        self.state = DriveEmpty()

    def device(self) -> str:
        return "D:"

    def fail_with(self, error: Exception) -> None:
        self._error = error

    def probe(self) -> DriveState:
        if self._error:
            raise self._error
        return self.state


class FakeFetch:
    """A `Fetch` (download) that serves bytes from a dict and records the URLs asked for."""

    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files
        self.calls: list[str] = []
        self._once: dict[str, bytes | Exception] = {}

    def serve_once(self, url: str, data: bytes) -> None:
        self._once[url] = data

    def fail_once(self, url: str, error: Exception) -> None:
        self._once[url] = error

    def __call__(self, url: str, dest: Path, progress: Callable[[int, int | None], None]) -> None:
        self.calls.append(url)
        data = self._once.pop(url, None)
        if data is None:
            data = self.files[url]
        if isinstance(data, Exception):
            dest.write_bytes(b"part")
            raise data
        half = len(data) // 2
        dest.write_bytes(data[:half])
        progress(half, len(data))
        dest.write_bytes(data)
        progress(len(data), len(data))


DATA = Path(__file__).parent / "data"


def _lines(name: str) -> list[str]:
    return (DATA / name).read_text(encoding="utf-8").splitlines()


# LibreDrive lines (notes/research/makemkvcon.md §6; MSG codes unverified, AMA keys on text).
_LIBREDRIVE_ON = ('MSG:1011,0,1,"Using LibreDrive mode (v06.3 id=0123456789AB)","%1",'
                  '"Using LibreDrive mode (v06.3 id=0123456789AB)"')
_LIBREDRIVE_REQUIRED = ('MSG:5097,0,0,"LibreDrive compatible drive is required to open this '
                        'disc - video can\'t be decrypted","LibreDrive compatible drive is '
                        'required to open this disc - video can\'t be decrypted"')


class FakeMakemkv:
    """A `Streamer` that plays makemkvcon against the Disc in a FakeDrive.

    `info` answers with the captured scan; `mkv <id> <dir>` writes the Title's
    file into <dir> and streams progress. A rip holds at 50% until `release()`
    (so tests can look at a Rip in progress) or until the Disc leaves the drive.
    """

    def __init__(self, drive: FakeDrive) -> None:
        self.drive = drive
        self.calls: list[list[str]] = []
        self.licence_ok = True
        self.fail_title: int | None = None
        self.ripped_ids: list[int] = []
        self.ripping = False
        self.disc_name: str | None = None  # replaces the scan's Disc + volume name (CINFO 2/32)
        self.scan_file = "makemkv-info-bd.txt"  # what `info` prints (tests/data/)
        # A UHD scan says "Using LibreDrive mode"; this many `info` runs refuse it instead.
        self.libredrive_refusals = 0
        self._go = threading.Event()

    def release(self) -> None:
        self._go.set()

    def __call__(self, args: Sequence[str], on_line: Callable[[str], None],
                 cwd: Path | None = None) -> int:
        args = list(args)
        self.calls.append(args)
        if not self.licence_ok:
            for ln in _lines("makemkv-licence-too-old.txt"):
                on_line(ln)
            return 127
        if "info" in args:
            out = _lines(self.scan_file)
            if self.disc_name is not None:
                volume = self.disc_name.upper().replace(" ", "_")
                out = [f'CINFO:2,0,"{self.disc_name}"' if ln.startswith("CINFO:2,") else
                       f'CINFO:32,0,"{volume}"' if ln.startswith("CINFO:32,") else ln
                       for ln in out]
            if args[-1] == "disc:9999":
                out = [ln for ln in out if ln.startswith(("MSG:1005", "DRV:"))]
            elif (isinstance(self.drive.state, DiscPresent)
                  and self.drive.state.disc_type == DiscType.UHD):
                if self.libredrive_refusals > 0:
                    self.libredrive_refusals -= 1
                    out = [ln for ln in out if ln.startswith(("MSG:1005", "DRV:"))] + [
                        _LIBREDRIVE_REQUIRED, 'MSG:5010,0,0,"Failed to open disc",'
                                              '"Failed to open disc"', "TCOUNT:0"]
                else:
                    i = next(i for i, ln in enumerate(out) if ln.startswith("PRGT:"))
                    out = [*out[:i], _LIBREDRIVE_ON, *out[i:]]
            for ln in out:
                on_line(ln)
            return 0
        i = args.index("mkv")
        title_id, dest = int(args[i + 2]), Path(args[i + 3])
        out = _lines("makemkv-mkv-title.txt")
        start = out.index("PRGV:32768,32768,65536")
        for ln in out[: start + 1]:
            on_line(ln)
        f = dest / f"Example_Movie_t{title_id:02d}.mkv"
        f.write_bytes(b"partial")
        self.ripping = True
        while not self._go.wait(0.01):
            on_line("PRGV:32768,32768,65536")  # lets the caller abort us
            if not isinstance(self.drive.state, DiscPresent):
                on_line('MSG:5010,0,0,"Failed to open disc","Failed to open disc"')
                return 1
        self.ripping = False
        if title_id == self.fail_title:
            on_line('MSG:2003,0,3,"Error \'Scsi error - MEDIUM ERROR\' occurred while reading '
                    '\'/BDMV/STREAM/00020.m2ts\' at offset \'1048576\'","Error \'%1\' occurred '
                    'while reading \'%2\' at offset \'%3\'","Scsi error - MEDIUM ERROR",'
                    '"/BDMV/STREAM/00020.m2ts","1048576"')
            on_line('MSG:5037,516,2,"Copy complete. 0 titles saved, 1 failed.",'
                    '"Copy complete. %1 titles saved, %2 failed.","0","1"')
            return 0
        for ln in out[start + 1:]:
            on_line(ln)
        f.write_bytes(b"mkv")
        self.ripped_ids.append(title_id)
        return 0


class FakeCyanrip:
    """A `Streamer` that behaves like cyanrip 0.9.3.1 for `-I` and for a Rip.

    Output lines use cyanrip's real formats (see tests/data/cyanrip/). A Rip
    writes NN.flac, rip.cue and rip.log into `cwd / <-D value>`.
    `hold_at=n` pauses the Rip half-way through track n until `release()`.
    """

    def __init__(self, drive: FakeDrive) -> None:
        self.drive = drive
        self.enhanced_cd = False  # an UnrecognisedDisc that is really an enhanced CD
        self.calls: list[list[str]] = []
        self.disc_id = "iV4zYu5_g1huHgbfxS6qgxQBL_A-"  # MusicBrainz Disc ID
        self.tracks: list[tuple[int, float]] = [(1, 200.0), (2, 100.0), (3, 300.0)]
        self.preemphasis: set[int] = set()
        self.data_track: int | None = None
        self.ar_confidence: dict[int, int] = {}  # track -> confidence; absent = mismatch
        self.in_accuraterip = True
        self.read_errors_in: int | None = None   # track whose frames can't be read
        self.installed = True
        self.no_disc = False
        self.hold_at: int | None = None
        self._held = threading.Event()
        self._go = threading.Event()

    def release(self) -> None:
        self._go.set()

    def wait_until_held(self, timeout: float = 3.0) -> None:
        assert self._held.wait(timeout), "Rip never reached the hold point"

    def __call__(self, args: Sequence[str], on_line: Callable[[str], None],
                 cwd: Path | None = None) -> int:
        self.calls.append(list(args))
        if not self.installed:
            raise FileNotFoundError(args[0])
        if self.no_disc:
            on_line("Unable to open device!")
            return 1
        if isinstance(self.drive.state, UnrecognisedDisc) and not self.enhanced_cd:
            on_line("Unable to get CD TOC: no audio tracks")
            return 1
        header = ["cyanrip 0.9.3.1 (fake)", "System device:  \\\\.\\D:",
                  "Device model:   PIONEER BD-RW   BDR-S11J 1.01 SCSI CD-ROM",
                  "Offset:         +667 samples", f"Disc tracks:    {len(self.tracks)}",
                  f"DiscID:         {self.disc_id}",
                  f"AccurateRip:    {'found' if self.in_accuraterip else 'not found'}", "",
                  "Gaps:"]
        if any(n == 0 for n, _ in self.tracks):
            frames = int(dict(self.tracks)[0] * 75)
            header += [f"    {frames} frame unmarked gap between lead-in and track 1, marking as a pregap",
                       f"    {frames} frame pregap in track 1, splitting off into a new track, number 0"]
        else:
            header.append("    None signalled")
        header += ["", "Tracks:", ""]
        out: list[str] = list(header)
        for ln in header:
            on_line(ln)
        if "-I" in args:
            for n, secs in self.tracks:
                for ln in [f"Track {n} info:", *self._block(n, secs, ripped=False)]:
                    on_line(ln)
            if self.data_track:
                for ln in [f"Track {self.data_track} info:", "  Preemphasis:   none detected", "",
                           "  Properties:", "    Data bytes:  11665920 (11.13 Mib)", ""]:
                    on_line(ln)
            return 0
        out_dir = Path(cwd or ".") / args[list(args).index("-D") + 1]
        out_dir.mkdir(parents=True, exist_ok=True)
        errors = 0
        for n, secs in self.tracks:
            err = 0
            for pct in (25.0, 50.0, 75.0, 100.0):
                if n == self.read_errors_in and pct >= 50:
                    err += 1
                if pct == 75.0 and self.hold_at == n:
                    self._held.set()
                    self._go.wait(5)
                tail = f", errors - {err}" if err else ""
                on_line(f"Ripping and encoding track {n}, progress - {pct:.2f}%, ETA - 1m{tail}  ")
            (out_dir / f"{n:02d}.flac").write_bytes(flac_bytes(n, secs))
            errors += err
            if err:
                continue
            block = [f"Track {n} ripped and encoded successfully!",
                     *self._block(n, secs, ripped=True)]
            out += block
            for ln in block:
                on_line(ln)
        if self.data_track:
            out += [f"Track {self.data_track} is data:", "  Preemphasis:   none detected", "",
                    "  Properties:", "    Data bytes:  11665920 (11.13 Mib)", ""]
        footer = ["Paranoia status counts:", "  READ:          36475", "",
                  f"Ripping errors: {errors}", "Ripping finished at 2026-11-04T14:52:09"]
        out += footer
        for ln in footer:
            on_line(ln)
        (out_dir / "rip.log").write_text("\n".join(out) + "\nLog FUN512: fake\n", encoding="utf-8")
        cue = ['REM DISCID "8A0B2C0C"']
        for n, _ in self.tracks:
            cue += [f'FILE "{n:02d}.flac" WAVE', f"  TRACK {n:02d} AUDIO", "    INDEX 01 00:00:00"]
        if self.data_track:
            cue += ['FILE "data.bin" BINARY', f"  TRACK {self.data_track:02d} MODE1/2352",
                    "    INDEX 01 00:00:00"]
        (out_dir / "rip.cue").write_text("\n".join(cue) + "\n", encoding="utf-8")
        return 1 if errors else 0

    def _block(self, n: int, secs: float, ripped: bool) -> list[str]:
        pre = "present (TOC)" if n in self.preemphasis else "none detected"
        lines = [f"  Preemphasis:   {pre}", "", "  Properties:",
                 f"    Samples:     {int(secs * 44100)}", ""]
        if ripped:
            if self.in_accuraterip:
                lines.append("  Accurip:       disc found in database (max confidence: 12)")
                conf = self.ar_confidence.get(n)
                verdict = f"(accurately ripped, confidence {conf})" if conf else \
                    "(not found, either a new pressing, or bad rip)"
                lines += [f"    Accurip v1:  85BCC10B {verdict}",
                          f"    Accurip v2:  1DE39467 {verdict}"]
            else:
                lines += ["  Accurip:       not found", "    Accurip v1:  85BCC10B"]
        return lines + [""]


def flac_bytes(n: int, seconds: float) -> bytes:
    """A minimal valid FLAC file (STREAMINFO only, no audio frames) that taggers accept."""
    samples = int(seconds * 44100)
    packed = (44100 << 44) | (1 << 41) | (15 << 36) | samples  # rate, stereo, 16-bit, length
    info = (4096).to_bytes(2, "big") * 2 + bytes(6) + packed.to_bytes(8, "big") \
        + n.to_bytes(16, "big")  # "MD5" slot: keeps each track's bytes distinct
    return b"fLaC" + bytes([0x80, 0, 0, len(info)]) + info


class FakeWeb:
    """MusicBrainz, the Cover Art Archive and Plex, as an httpx transport.

    MusicBrainz is offline until a test sets `musicbrainz[disc_id]` (a response
    dict, or an HTTP status). `covers[release_id]` = image bytes. Plex requests
    are recorded in `plex_requests`; its libraries are `plex_sections`.
    """

    def __init__(self) -> None:
        self.musicbrainz: dict[str, dict | int] = {}
        self.covers: dict[str, bytes] = {}
        self.plex_sections = [{"key": "3", "type": "artist", "title": "Music",
                               "Location": [{"id": 1, "path": "/volume1/media/Music"}]},
                              {"key": "1", "type": "movie", "title": "Movies",
                               "Location": [{"id": 2, "path": "/volume1/media/Movies"}]}]
        self.plex_requests: list[httpx.Request] = []
        self.requests: list[httpx.Request] = []
        # TMDB: search results per (case-folded) query, /movie/{id} details by id.
        self.tmdb_search: dict[str, list[dict]] = {}
        self.tmdb_movies: dict[int, dict] = {}
        self.tmdb_offline = False
        self.tmdb_requests: list[httpx.Request] = []
        # Notifications (#15): what Discord and ntfy were sent; `notify_status` = their answer.
        self.discord: list[httpx.Request] = []
        self.ntfy: list[httpx.Request] = []
        self.notify_status = 200

    def add_film(self, query: str, id_: int, title: str, runtime: int, year: int = 2016,
                 original_language: str = "en", original_title: str | None = None,
                 director: str = "") -> None:
        """TMDB knows this film, and finds it when searched for `query`."""
        date = f"{year}-11-10"
        self.tmdb_search.setdefault(query.casefold(), []).append(
            {"id": id_, "title": title, "original_title": original_title or title,
             "release_date": date, "original_language": original_language})
        self.tmdb_movies[id_] = {"id": id_, "title": title, "runtime": runtime,
                                 "original_title": original_title or title,
                                 "release_date": date, "original_language": original_language,
                                 "credits": {"crew": [{"job": "Director", "name": director}]
                                             if director else []}}

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = request.url
        if url.host == "musicbrainz.org":
            answer = self.musicbrainz.get(url.path.rsplit("/", 1)[-1])
            if answer is None:
                raise httpx.ConnectError("no network", request=request)
            if isinstance(answer, int):
                return httpx.Response(answer, json={"error": "Not Found"})
            return httpx.Response(200, json=answer)
        if url.host == "coverartarchive.org":
            release = url.path.split("/")[2]
            if release in self.covers and url.path.split("/")[1] == "release":
                return httpx.Response(200, content=self.covers[release],
                                      headers={"content-type": "image/jpeg"})
            return httpx.Response(404)
        if url.host == "api.themoviedb.org":
            self.tmdb_requests.append(request)
            if self.tmdb_offline:
                raise httpx.ConnectError("no network", request=request)
            if url.path == "/3/search/movie":
                query = url.params.get("query", "").casefold()
                return httpx.Response(200, json={"page": 1, "results":
                                                 self.tmdb_search.get(query, [])})
            movie = self.tmdb_movies.get(int(url.path.rsplit("/", 1)[-1]))
            return httpx.Response(200, json=movie) if movie else httpx.Response(404)
        if url.host in ("discord.com", "ntfy.sh"):
            (self.discord if url.host == "discord.com" else self.ntfy).append(request)
            if self.notify_status == 0:
                raise httpx.ConnectError("no network", request=request)
            return httpx.Response(self.notify_status, json={})
        if url.host == "plex":
            self.plex_requests.append(request)
            if url.path == "/library/sections":
                return httpx.Response(200, json={"MediaContainer": {
                    "Directory": self.plex_sections}})
            return httpx.Response(200)
        return httpx.Response(404)


def probe_stream(index: int, kind: str, codec: str, lang: str = "", title: str = "",
                 **extra) -> dict:
    """One stream as ffprobe's JSON shows it (dispositions as keyword flags)."""
    disp = {k: int(extra.pop(k)) for k in ("default", "forced", "comment", "hearing_impaired",
                                           "attached_pic") if k in extra}
    return {"index": index, "codec_type": kind, "codec_name": codec,
            "tags": {k: v for k, v in (("language", lang), ("title", title)) if v},
            "disposition": {"default": 0, "forced": 0, "comment": 0, "hearing_impaired": 0,
                            "attached_pic": 0, **disp}, **extra}


# The real first frame of an HDR10 clip (tests/data/ffprobe/hdr10-source.json).
HDR10_FRAME: dict = json.loads((Path(__file__).parent / "data" / "ffprobe" / "hdr10-source.json")
                               .read_text(encoding="utf-8"))["frames"][0]


class FakeFfmpeg:
    """A `Streamer` playing ffprobe (answers `streams`) and an ffmpeg Encode.

    The Encode streams `-progress` blocks; with `hold` it stays at 40% until
    `release()`. It then writes the output file, or fails with `exit_code`.
    """

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.thumbnails: list[list[str]] = []  # Review stills (`-frames:v` to a .jpg), not Encodes
        self.thumbnail_exit_code = 0
        self.streams: list[dict] = [
            probe_stream(0, "video", "h264", height=1080),
            probe_stream(1, "audio", "truehd", "eng", "Surround 7.1", default=1),
            probe_stream(2, "audio", "ac3", "fra", "Surround 5.1"),
            probe_stream(3, "audio", "ac3", "eng", "Commentary"),
            probe_stream(4, "subtitle", "hdmv_pgs_subtitle", "eng"),
            probe_stream(5, "subtitle", "hdmv_pgs_subtitle", "fra"),
        ]
        self.duration = 7293.0
        # The first video frame `hdr.probe_args` sees (ffprobe JSON `frames[0]`): SDR by
        # default, `HDR10_FRAME` for a UHD. The Encode keeps it unless `encode_frame` is set.
        self.frame: dict = {"pix_fmt": "yuv420p", "color_range": "tv", "color_space": "bt709",
                            "color_primaries": "bt709", "color_transfer": "bt709"}
        self.encode_frame: dict | None = None
        self._frames: dict[str, dict] = {}  # Encode output path -> its first frame
        self.exit_code = 0
        self.hold = False
        self.encoding = threading.Event()  # set while an Encode is running
        self.sample_output: list[str] = []  # what each picture-analysis run prints (#10)
        self._go = threading.Event()

    def release(self) -> None:
        self._go.set()

    @staticmethod
    def _is_sample(args: Sequence[str]) -> bool:
        return list(args[-3:]) == ["-f", "null", "-"]

    def encodes(self) -> list[list[str]]:
        return [c for c in self.calls
                if "ffmpeg" in Path(c[0]).name.lower() and not self._is_sample(c)]

    def samples(self) -> list[list[str]]:
        """The picture-analysis runs (idet/cropdetect to the null muxer)."""
        return [c for c in self.calls if self._is_sample(c)]

    def _block(self, on_line: Callable[[str], None], fraction: float) -> None:
        for ln in ("frame=1000", "fps=48.0", f"out_time_us={int(self.duration * fraction * 1e6)}",
                   "speed=2.00x", "progress=continue"):
            on_line(ln)

    def __call__(self, args: Sequence[str], on_line: Callable[[str], None],
                 cwd: Path | None = None) -> int:
        args = list(args)
        if "-frames:v" in args and args[-1].endswith(".jpg"):  # a Review still, not analysis
            self.thumbnails.append(args)
            if not self.thumbnail_exit_code:
                Path(args[-1]).write_bytes(b"\xff\xd8 fake jpeg")
            return self.thumbnail_exit_code
        self.calls.append(args)
        if "ffprobe" in Path(args[0]).name.lower() and "-show_frames" in args:
            frame = self._frames.get(args[-1], self.frame)
            out = json.dumps({"frames": [frame], "streams": [self.streams[0]]}, indent=1)
            for ln in out.splitlines():
                on_line(ln)
            return 0
        if "ffprobe" in Path(args[0]).name.lower():
            out = json.dumps({"streams": self.streams, "chapters": [{"id": 0}, {"id": 1}],
                              "format": {"duration": str(self.duration)}}, indent=1)
            for ln in out.splitlines():
                on_line(ln)
            return 0
        if self._is_sample(args):
            for ln in self.sample_output:
                on_line(ln)
            return 0
        src, dest = Path(args[args.index("-i") + 1]), Path(args[-1])
        assert src.exists(), f"Encode source missing: {src}"
        self.encoding.set()
        try:
            self._block(on_line, 0.1)
            on_line("[hevc_nvenc @ 0000020] a harmless warning")
            while self.hold and not self._go.wait(0.01):
                self._block(on_line, 0.4)  # lets the caller abort us
            if self.exit_code:
                on_line("[hevc_nvenc @ 0000020] OpenEncodeSessionEx failed: unsupported device")
                return self.exit_code
            dest.write_bytes(b"HEVC " + src.name.encode())
            self._frames[str(dest)] = self.encode_frame or self.frame
            on_line("progress=end")
            return 0
        finally:
            self.encoding.clear()


class FakeTools:
    """One `Streamer` for the app, routing on the program: makemkvcon -> `makemkv`,
    ffmpeg/ffprobe -> `ffmpeg`, the rest -> `cyanrip`."""

    def __init__(self, makemkv: FakeMakemkv, cyanrip: FakeCyanrip,
                 ffmpeg: FakeFfmpeg | None = None) -> None:
        self.makemkv = makemkv
        self.cyanrip = cyanrip
        self.ffmpeg = ffmpeg or FakeFfmpeg()

    def __call__(self, args: Sequence[str], on_line: Callable[[str], None],
                 cwd: Path | None = None) -> int:
        name = Path(args[0]).name.lower()
        fake = (self.makemkv if "makemkv" in name else
                self.ffmpeg if "ffmpeg" in name or "ffprobe" in name else self.cyanrip)
        return fake(args, on_line, cwd)


class FakeDisk:
    """`shutil.disk_usage` for the scratch volume: 256 GB, empty unless a test fills it."""

    def __init__(self, total: int = 256 * 1000**3, used: int = 0) -> None:
        self.total = total
        self.used = used

    def __call__(self, path: Path) -> DiskUsage:
        return DiskUsage(self.total, self.used, self.total - self.used)


class FakeRunner:
    """A `Runner` that records commands and answers from a handler."""

    def __init__(self, handler: Callable[[Sequence[str]], ProcResult] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.handler = handler or (lambda args: ProcResult(0, ""))

    def __call__(self, args: Sequence[str]) -> ProcResult:
        self.calls.append(list(args))
        return self.handler(args)
