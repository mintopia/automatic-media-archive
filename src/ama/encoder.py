"""The one Encode, shared by films, their Extras and TV: one at a time, whoever asks.

ffprobe picks the streams (`encode.py`), the picture is sampled for bars and scan
type (`picture.py`), HDR10 is checked on both sides (`hdr.py`), and ffmpeg with
the configured encoder (`[encode]`, ADR 0010) writes `<name>.tmp.mkv`, renamed when
it is good.
"""

from __future__ import annotations

import asyncio
import collections
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from ama import encode, hdr, picture
from ama.config import EncodeConfig
from ama.db import Database
from ama.jobs import JobRecord, JobStatus, JobStore, TitleRecord
from ama.drive import DiscType
from ama.encode import EncodeProgress, ProgressReader
from ama.events import EventBus, Topic
from ama.proc import Streamer
from ama.retry import RetryLater
from ama.tools import ToolLookup, ToolUnavailable

PUBLISH_EVERY_SECONDS = 0.5
LOG_TAIL = 15  # ffmpeg warning lines kept for the Job log when an Encode fails
# What the Encode pipeline's progress shows on: the queue, the Job pages, History, Review.
PIPELINE_TOPICS = (Topic.ENCODE, Topic.RIP, Topic.FILED, Topic.REVIEW)


class EncodeStatus(StrEnum):
    """Where a queued Title (a film, an Extra, an Episode) is in the Encode queue."""

    QUEUED = "queued"
    ENCODING = "encoding"
    ENCODED = "encoded"  # waiting to be filed
    FAILED = "failed"
    FILED = "filed"


class EncodeQueue:
    """The queue SQL every Encode table (`movies`, `tv_titles`, `extras`) shares."""

    def __init__(self, db: Database, table: str, column: str) -> None:
        self._db = db
        self._table = table    # a fixed name from code, never user input
        self._column = column  # its status column

    def requeue(self, *statuses: EncodeStatus) -> list[int]:
        """Put rows in `statuses` of Jobs still on their way (`ripped`) back in the queue;
        the Jobs affected."""
        marks = ", ".join("?" * len(statuses))
        where = (f"WHERE {self._column} IN ({marks}) "
                 "AND job_id IN (SELECT id FROM jobs WHERE status = 'ripped')")
        rows = self._db.execute(f"SELECT DISTINCT job_id FROM {self._table} {where}",
                                statuses).fetchall()
        self._db.execute(f"UPDATE {self._table} SET {self._column} = ? {where}",
                         (EncodeStatus.QUEUED, *statuses))
        return [r[0] for r in rows]

    def waiting(self, cols: str, order: str) -> list[tuple]:
        """Rows of Jobs still on their way to the Archive (`ripped`), in `order`."""
        return self._db.execute(
            f"SELECT {cols} FROM {self._table} q JOIN jobs d ON d.id = q.job_id "
            f"WHERE d.status = ? ORDER BY {order}", (JobStatus.RIPPED,)).fetchall()


@dataclass(frozen=True)
class TitleEncode:
    """The Encode in progress (memory only), for the UI."""

    job: JobRecord
    name: str  # what is being encoded: "Arrival (2016)", "The Office - s01e04 - The Quiz"
    progress: EncodeProgress
    title_number: int = 0  # the Title of `disc` being encoded


UHD_MIN_HEIGHT = 1500  # taller than this is a 4K (UHD) picture, whatever the Disc looked like

_FFMPEG_ERROR = re.compile(r"\b(error|invalid|failed|cannot|could not|conversion failed)\b",
                           re.IGNORECASE)


def is_ffmpeg_error(line: str) -> bool:
    """An ffmpeg output line worth marking in Logs (its errors carry these words)."""
    return bool(_FFMPEG_ERROR.search(line))


def encode_disc_type(disc_type: DiscType, video_height: int) -> DiscType:
    """The Disc Type to Encode as: a 4K Main Feature is a UHD's (BD/UHD detection is a guess)."""
    return DiscType.UHD if video_height > UHD_MIN_HEIGHT else disc_type


class _Aborted(Exception):
    pass


class Encoder:
    def __init__(self, jobs: JobStore, bus: EventBus, cfg: EncodeConfig, tool: ToolLookup,
                 streamer: Streamer, clock: Callable[[], float] = time.monotonic,
                 hold: Callable[[], bool] = lambda: False,
                 job_config: Callable[[JobRecord], EncodeConfig] | None = None) -> None:
        self._hold = hold  # start no new Encode (a restart is waiting)
        # A Job's Encode settings, locked as its first Encode starts (job_settings); else cfg.
        self._job_config = job_config or (lambda rec: self.cfg)
        self._jobs = jobs
        self._bus = bus
        self.cfg = cfg  # live: `Services.apply_live` replaces it
        self._tool = tool
        self._stream = streamer
        self._clock = clock
        self.current: TitleEncode | None = None
        self.lock = asyncio.Lock()  # one Encode at a time, whoever asks
        self._abort = False
        self._last_publish = 0.0
        self._loop: asyncio.AbstractEventLoop | None = None

    def tools(self) -> tuple[Path, Path]:
        """(ffmpeg, ffprobe); RetryLater while they aren't ready."""
        try:
            return self._tool("ffmpeg"), self._tool("ffprobe")
        except ToolUnavailable as e:
            raise RetryLater(f"{e.name} isn't ready yet") from None

    async def encode_title(self, rec: JobRecord, title: TitleRecord, name: str,
                           original_language: str, done: Path, ffmpeg: Path, ffprobe: Path,
                           extra: bool = False) -> int | None:
        """Encode one ripped Title of `rec` to `done` (written as `<stem>.tmp.mkv`, then
        renamed), tagged `name`. Returns its picture height, or None if the Encode failed
        (logged; the Rip is kept). One Encode at a time across callers (`encoder`).
        `extra`: a film's Extra, Encoded as what it is (a UHD's HD Extra gets BD's CQ)
        and left out if it fails."""
        async with self.lock:
            while self._hold():
                await asyncio.sleep(0.5)
            return await self._encode_title(rec, title, name, original_language, done,
                                            ffmpeg, ffprobe, extra)

    async def _encode_title(self, rec: JobRecord, title: TitleRecord, name: str,
                            original_language: str, done: Path, ffmpeg: Path, ffprobe: Path,
                            extra: bool) -> int | None:
        then = (f"The Extra “{name}” is left out; the film is filed without it" if extra
                else "The Rip is kept; the Encode will be tried again when the app restarts")
        cfg = self._job_config(rec)  # fixed for this Job once its Encode starts (#30)
        src = rec.scratch_dir / title.file
        tmp = done.with_name(f"{done.stem}.tmp.mkv")
        self._abort = False
        self.current = TitleEncode(rec, name, EncodeProgress(0.0), title.number)
        self._jobs.encode_started(rec.id, title.number)
        self._publish()
        try:
            probe_lines: list[str] = []
            code = await asyncio.to_thread(self._stream, encode.ffprobe_args(ffprobe, src),
                                           probe_lines.append)
            try:
                probe = encode.parse_probe("\n".join(probe_lines))
                sel = encode.select_streams(probe, original_language,
                                            encode.TrackPolicy.of(cfg))
            except ValueError as e:
                return self._failed(rec, then, f"Couldn't read Title {title.number} ({e}; ffprobe exit "
                                         f"{code})", probe_lines[-LOG_TAIL:])
            source_hdr = await self._probe_hdr(ffprobe, src)
            if isinstance(source_hdr, str):
                return self._failed(rec, then, f"Couldn't read the colour of Title {title.number} "
                                         f"({source_hdr})", [])
            kind = encode_disc_type(
                DiscType.BD if extra and rec.disc_type == DiscType.UHD else rec.disc_type,
                probe.height)
            if kind != rec.disc_type and not extra:
                self._jobs.log(rec.id, f"The Disc looked like a {rec.disc_type.long_name}, but "
                                        f"its Main Feature is 4K, so it is encoded as a UHD")
            cq = encode.cq_for(cfg.cq, kind)
            max_resolution = getattr(cfg.max_resolution, kind.name.lower())
            pic = await self._analyse_picture(rec, ffmpeg, src, probe)
            self._jobs.log(rec.id, pic.describe())
            scaled = (f", at most {max_resolution}"
                      if encode.scale_filter(max_resolution) else "")
            stereo = " (plus an AAC stereo copy)" if sel.stereo else ""
            self._jobs.log(rec.id, f"Encoding Title {title.number} as {name}: "
                                    f"{encode.ENCODERS[cfg.encoder].label} 10-bit, quality "
                                    f"{cq}, {encode.SPEED_LABELS[cfg.speed].lower()}{scaled}; "
                                    f"keeping {len(sel.audio)} audio{stereo} and "
                                    f"{len(sel.subtitles)} subtitle tracks, {probe.chapters} "
                                    "chapters")
            if source_hdr.is_hdr10:
                dropped = [n for n, on in (("Dolby Vision", source_hdr.dolby_vision),
                                           ("HDR10+", source_hdr.hdr10_plus)) if on]
                self._jobs.log(rec.id, f"HDR10: {source_hdr}" + (
                    f"; {' and '.join(dropped)} metadata will be dropped (ADR-0003)"
                    if dropped else ""))
            reader = ProgressReader(probe.duration_s or title.duration_s)
            tail: collections.deque[str] = collections.deque(maxlen=LOG_TAIL)

            def on_line(line: str) -> None:
                if self._abort:
                    raise _Aborted
                if not reader.is_progress(line):
                    tail.append(line)
                    self._jobs.step_output(rec.id, line, error=is_ffmpeg_error(line))
                    return
                p = reader.feed(line)
                if p is not None and self.current is not None:
                    self.current = TitleEncode(rec, name, p, title.number)
                    self._publish_soon()

            tmp.unlink(missing_ok=True)
            started = self._clock()
            args = encode.ffmpeg_args(ffmpeg, src, tmp, sel, cq, name, pic.filters,
                                      hdr=source_hdr if source_hdr.is_hdr10 else None,
                                      encoder=cfg.encoder, speed=cfg.speed,
                                      max_resolution=max_resolution)
            try:
                code = await asyncio.to_thread(self._stream, args, on_line)
            except asyncio.CancelledError:
                self._abort = True  # kills ffmpeg; recover() requeues it next start
                raise
            except OSError as e:
                return self._failed(rec, then, f"ffmpeg couldn't be started ({e.strerror or e})", [])
            if code != 0 or not tmp.exists():
                tmp.unlink(missing_ok=True)
                return self._failed(rec, then, f"ffmpeg stopped with exit code {code}", list(tail),
                                    code)
            if source_hdr.is_hdr10:
                encoded_hdr = await self._probe_hdr(ffprobe, tmp)
                lost = ([f"ffprobe couldn't read it ({encoded_hdr})"]
                        if isinstance(encoded_hdr, str)
                        else hdr.differences(source_hdr, encoded_hdr))
                if lost:
                    tmp.unlink(missing_ok=True)
                    return self._failed(rec, then, "the Encode didn't keep the HDR10 metadata: "
                                             + "; ".join(lost), [])
                self._jobs.log(rec.id, f"HDR10 metadata kept: {encoded_hdr}")
            os.replace(tmp, done)
            minutes = max(1, round((self._clock() - started) / 60))
            self._jobs.log(rec.id, f"Encode{f' of the Extra “{name}”' if extra else ''} "
                                    f"finished in {minutes} min "
                                    f"({done.stat().st_size / 1000**3:.1f} GB)")
            self._jobs.encode_finished(rec.id, title.number)
            return probe.height
        finally:
            self.current = None

    async def _analyse_picture(self, rec: JobRecord, ffmpeg: Path, src: Path,
                               probe: encode.Probe) -> picture.Picture:
        """Sample the Title for black bars and, on a DVD, its scan type. A failed sample
        counts for nothing: the Encode then crops less, never more."""
        video = probe.video
        assert video is not None  # select_streams already insisted on one
        dvd = rec.disc_type == DiscType.DVD
        runs: list[list[str]] = []
        for at in picture.sample_times(probe.duration_s):
            lines: list[str] = []

            def on_line(line: str, lines: list[str] = lines) -> None:
                if self._abort:
                    raise _Aborted
                lines.append(line)

            try:
                await asyncio.to_thread(self._stream,
                                        picture.sample_args(ffmpeg, src, at, idet=dvd), on_line)
            except asyncio.CancelledError:
                self._abort = True
                raise
            except OSError:
                pass
            runs.append(lines)
        return picture.analyse(runs, width=video.width, height=video.height,
                               fps=video.frame_rate, detect_scan=dvd)

    async def _probe_hdr(self, ffprobe: Path, path: Path) -> hdr.HdrInfo | str:
        """The video's colour and HDR10 metadata, or why it couldn't be read."""
        lines: list[str] = []
        code = await asyncio.to_thread(self._stream, hdr.probe_args(ffprobe, path), lines.append)
        try:
            return hdr.parse_hdr("\n".join(lines))
        except ValueError as e:
            return f"{e}; ffprobe exit {code}"

    def _failed(self, rec: JobRecord, then: str, why: str, tail: list[str],
                exit_code: int | None = None) -> None:
        for line in tail:  # already in the Step's output in Logs
            self._jobs.log(rec.id, line, error=True, in_step=False)
        self._jobs.log(rec.id, f"The Encode didn't work: {why}. {then}", error=True)
        self._jobs.end_step(rec.id, failed=True, exit_code=exit_code,
                            result=f"The Encode didn't work: {why}")

    def _publish(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._last_publish = self._clock()
        for topic in PIPELINE_TOPICS:
            self._bus.publish(topic)

    def _publish_soon(self) -> None:
        """From the ffmpeg thread: publish on the loop, at most every PUBLISH_EVERY_SECONDS."""
        if self._clock() - self._last_publish < PUBLISH_EVERY_SECONDS or self._loop is None:
            return
        self._last_publish = self._clock()
        self._loop.call_soon_threadsafe(self._bus.publish, Topic.ENCODE)
