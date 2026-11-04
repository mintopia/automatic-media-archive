"""Fakes for the hardware/OS/process boundary. Tests never touch real devices."""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from pathlib import Path

from ama.drive import DiscPresent, DiscType, DriveEmpty, DriveState, UnrecognisedDisc
from ama.proc import ProcResult


class FakeDrive:
    """A `DriveProbe` whose contents the test controls."""

    def __init__(self) -> None:
        self.state: DriveState = DriveEmpty()
        self._error: Exception | None = None
        self.ejected = 0
        self.stuck = False  # eject() fails and the Disc stays in

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


DATA = Path(__file__).parent / "data"


def _lines(name: str) -> list[str]:
    return (DATA / name).read_text(encoding="utf-8").splitlines()


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
            out = _lines("makemkv-info-bd.txt")
            if args[-1] == "disc:9999":
                out = [ln for ln in out if ln.startswith(("MSG:1005", "DRV:"))]
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
                  "DiscID:         iV4zYu5_g1huHgbfxS6qgxQBL_A-",
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
            (out_dir / f"{n:02d}.flac").write_bytes(b"fLaC")
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


class FakeTools:
    """One `Streamer` for the app: makemkvcon calls go to `makemkv`, the rest to `cyanrip`."""

    def __init__(self, makemkv: FakeMakemkv, cyanrip: FakeCyanrip) -> None:
        self.makemkv = makemkv
        self.cyanrip = cyanrip

    def __call__(self, args: Sequence[str], on_line: Callable[[str], None],
                 cwd: Path | None = None) -> int:
        fake = self.makemkv if "makemkv" in Path(args[0]).name.lower() else self.cyanrip
        return fake(args, on_line, cwd)


class FakeRunner:
    """A `Runner` that records commands and answers from a handler."""

    def __init__(self, handler: Callable[[Sequence[str]], ProcResult] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.handler = handler or (lambda args: ProcResult(0, ""))

    def __call__(self, args: Sequence[str]) -> ProcResult:
        self.calls.append(list(args))
        return self.handler(args)
