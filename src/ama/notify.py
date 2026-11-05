"""Push notifications to Discord (webhook) and ntfy (topic) that pull people back to the UI.

Four events, read off Job status changes (`JobStore.statuses()`) whenever
anything is published on the bus, so no pipeline stage has to call this:

- Rip done: a Job's Rip finished and its Disc was ejected (left `ripping` for
  `ripped`/`review`/`filed`), so the next Disc can go in.
- Review needed: a Job entered `review`.
- Filed: a Job became `filed`, unless nothing in it was ripped (every Title
  Skipped).
- Job failed: a Job became `failed` (not when the user discarded it in Review).

A channel is on when its config value is set (`discord.webhook_url`,
`ntfy.topic`), else silently absent. Sending happens off the notifier's own
task, every channel on its own thread at the same time with its own 10 s
timeout, so a slow or dead channel never delays another. Every failure is
logged and dropped: a notification never blocks or breaks the pipeline. Discs
already in a state at startup don't notify again. Log lines never contain the webhook URL or topic
(both are secrets).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

import httpx

from ama.config import Config
from ama.drive import DiscType
from ama.jobs import JobRecord, JobStatus, JobStore, FailureKind, TitleStatus
from ama.events import EventBus
from ama.problems import Problem, Problems

log = logging.getLogger(__name__)

TIMEOUT = 10.0


class Event(StrEnum):
    RIP_DONE = "rip_done"
    REVIEW_NEEDED = "review_needed"
    JOB_FILED = "job_filed"
    JOB_FAILED = "job_failed"


_DONE = {JobStatus.RIPPED, JobStatus.REVIEW, JobStatus.FILED}


def changes(before: Mapping[int, JobStatus],
            after: Mapping[int, JobStatus]) -> list[tuple[int, Event]]:
    """The events between two `statuses()` snapshots, oldest Job first."""
    out: list[tuple[int, Event]] = []
    for job_id in sorted(after):
        prev, cur = before.get(job_id), after[job_id]
        if prev == cur:
            continue
        if prev in (None, JobStatus.RIPPING) and cur in _DONE:
            out.append((job_id, Event.RIP_DONE))
        if cur == JobStatus.REVIEW:
            out.append((job_id, Event.REVIEW_NEEDED))
        if cur == JobStatus.FILED:
            out.append((job_id, Event.JOB_FILED))
        if cur == JobStatus.FAILED:
            out.append((job_id, Event.JOB_FAILED))
    return out


@dataclass(frozen=True)
class Notification:
    event: Event
    title: str
    message: str


def _subject(rec: JobRecord) -> str:
    return f"{rec.disc_type.long_name} “{rec.label}”" if rec.label else rec.disc_type.long_name


def notification(event: Event, rec: JobRecord) -> Notification:
    match event:
        case Event.RIP_DONE:
            return Notification(event, "Rip done · insert the next one",
                                f"{_subject(rec)} is ripped and ejected. Insert the next Disc.")
        case Event.REVIEW_NEEDED:
            return Notification(event, "Review needed",
                                f"{_subject(rec)} needs Review before it can be filed.")
        case Event.JOB_FILED:
            return Notification(event, "Filed", f"{_subject(rec)} is filed as {rec.title}.")
        case Event.JOB_FAILED:
            why = " ".join(p for p in (rec.failure.headline, rec.failure.advice) if p) \
                if rec.failure else ""
            return Notification(event, "Job failed", f"{_subject(rec)} failed. {why}".strip())


class Channel(Protocol):
    name: str

    def send(self, note: Notification) -> None:
        """Deliver it, or raise."""


# Discord embed colours / ntfy tags+priority per event.
_COLOUR = {Event.RIP_DONE: 0x2E7D32, Event.REVIEW_NEEDED: 0xF9A825, Event.JOB_FILED: 0x1565C0,
           Event.JOB_FAILED: 0xC62828}
_TAGS = {Event.RIP_DONE: "white_check_mark", Event.REVIEW_NEEDED: "eyes",
         Event.JOB_FILED: "file_folder", Event.JOB_FAILED: "warning"}
_PRIORITY = {Event.RIP_DONE: 3, Event.REVIEW_NEEDED: 4, Event.JOB_FILED: 3, Event.JOB_FAILED: 4}


@dataclass
class Discord:
    http: httpx.Client
    webhook_url: str
    name: str = "Discord"

    def send(self, note: Notification) -> None:
        # wait=true: otherwise a message Discord drops still answers 204.
        self.http.post(self.webhook_url, params={"wait": "true"}, timeout=TIMEOUT, json={
            "embeds": [{"title": note.title, "description": note.message,
                        "color": _COLOUR[note.event]}],
            "allowed_mentions": {"parse": []},  # a Disc label can't ping @everyone
        }).raise_for_status()


@dataclass
class Ntfy:
    http: httpx.Client
    url: str
    topic: str
    name: str = "ntfy"

    def send(self, note: Notification) -> None:
        # JSON publish to the server root: non-ASCII titles need no header encoding.
        self.http.post(self.url.rstrip("/") + "/", timeout=TIMEOUT, json={
            "topic": self.topic, "title": note.title, "message": note.message,
            "tags": [_TAGS[note.event]], "priority": _PRIORITY[note.event],
        }).raise_for_status()


def channels(cfg: Config, http: httpx.Client) -> list[Channel]:
    """The configured channels; one without its config value is simply not there."""
    out: list[Channel] = []
    if cfg.discord.webhook_url:
        out.append(Discord(http, cfg.discord.webhook_url))
    if cfg.ntfy.topic:
        out.append(Ntfy(http, cfg.ntfy.url, cfg.ntfy.topic))
    return out


def _why(e: Exception) -> str:
    """A failure, without the request URL (it holds the webhook token / topic)."""
    if isinstance(e, httpx.HTTPStatusError):
        return f"HTTP {e.response.status_code}"
    return type(e).__name__


def _send_all(ch: Channel, notes: Sequence[Notification]) -> str | None:
    """Why the last of `notes` failed on `ch`, or None if it went through."""
    why = None
    for note in notes:
        try:
            ch.send(note)
        except Exception as e:  # noqa: BLE001 - nothing here may break the pipeline
            why = _why(e)
            log.warning("Couldn't send the %s notification to %s: %s", note.title, ch.name, why)
        else:
            why = None
    return why


def _empty(rec: JobRecord) -> bool:
    """A video Job with no Title ripped (every Title Skipped); a CD's tracks aren't Titles."""
    return rec.disc_type != DiscType.CD and not any(
        t.status == TitleStatus.RIPPED for t in rec.titles)


class Notifier:
    """Background task: watches Job statuses after every bus event and notifies."""

    def __init__(self, jobs: JobStore, bus: EventBus, channels: Sequence[Channel],
                 problems: Problems | None = None) -> None:
        self._jobs = jobs
        self._problems = problems
        self._failing: dict[str, str] = {}  # channel name -> why its last send failed
        self._bus = bus
        self.channels = list(channels)

    def send(self, notes: Sequence[Notification]) -> None:
        """Every note to every channel, all channels at once; failures are logged and shown
        as a banner until a send works again, never raised."""
        chans = list(self.channels)
        with ThreadPoolExecutor(max(1, len(chans)), thread_name_prefix="notify") as pool:
            results = list(pool.map(lambda ch: _send_all(ch, notes), chans))
        for ch, why in zip(chans, results):
            if why is None:
                self._failing.pop(ch.name, None)
            else:
                self._failing[ch.name] = why
        if self._problems is not None:
            if self._failing:
                self._problems.report(Problem.NOTIFY, ", ".join(
                    f"{name}: {why}" for name, why in self._failing.items()))
            else:
                self._problems.resolved(Problem.NOTIFY)

    def _notes(self, events: list[tuple[int, Event]]) -> list[Notification]:
        notes = []
        for job_id, event in events:
            rec = self._jobs.get(job_id)
            if rec is None:
                continue
            if event == Event.JOB_FAILED and rec.failure \
                    and rec.failure.kind in (FailureKind.DISCARDED, FailureKind.SCRATCH_CLEANED):
                continue  # the user's own decision in Review, or housekeeping
            if rec.all_skipped:
                continue  # the user's own decision during the Rip: nothing to go back for
            if event == Event.JOB_FILED and _empty(rec):
                continue
            notes.append(notification(event, rec))
        return notes

    async def run(self) -> None:
        # Runs even with no channels: Settings can add one at any time (`channels` is live).
        with self._bus.subscribe() as topics:
            seen = self._jobs.statuses()
            while True:
                await topics.get()
                while not topics.empty():  # one look covers a burst of events
                    topics.get_nowait()
                try:
                    now = self._jobs.statuses()
                    notes = self._notes(changes(seen, now))
                    seen = now
                except Exception:  # noqa: BLE001
                    log.exception("Couldn't check Jobs for notifications")
                    continue
                if notes:
                    await asyncio.to_thread(self.send, notes)
