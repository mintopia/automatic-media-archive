"""Alerts on Job status changes, to Discord, ntfy and a Webhook."""

from __future__ import annotations

import asyncio
import logging
import socket
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

import httpx

from ama.config import Config, WebConfig
from ama.jobs import USER_STOPPED, JobRecord, JobStatus, JobStore
from ama.events import EventBus
from ama.problems import Problem, Problems

log = logging.getLogger(__name__)

TIMEOUT = 10.0


class Event(StrEnum):
    RIP_DONE = "rip_done"
    REVIEW_NEEDED = "review_needed"
    JOB_ARCHIVED = "job_archived"
    JOB_FAILED = "job_failed"


_DONE = {JobStatus.RIPPED, JobStatus.REVIEW, JobStatus.ARCHIVED}


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
        if cur == JobStatus.ARCHIVED:
            out.append((job_id, Event.JOB_ARCHIVED))
        if cur == JobStatus.FAILED:
            out.append((job_id, Event.JOB_FAILED))
    return out


@dataclass(frozen=True)
class Notification:
    event: Event
    title: str
    message: str
    job: JobRecord | None = None
    at: datetime = field(default_factory=lambda: datetime.now(UTC))


def _subject(rec: JobRecord) -> str:
    return f"{rec.disc_type.long_name} “{rec.label}”" if rec.label else rec.disc_type.long_name


def notification(event: Event, rec: JobRecord) -> Notification:
    match event:
        case Event.RIP_DONE:
            title = "Rip done · insert the next one"
            message = f"{_subject(rec)} is ripped and ejected. Insert the next Disc."
        case Event.REVIEW_NEEDED:
            title = "Review needed"
            message = f"{_subject(rec)} needs Review before it can be archived."
        case Event.JOB_ARCHIVED:
            title = "Archived"
            message = f"{_subject(rec)} is archived as {rec.title}."
        case Event.JOB_FAILED:
            why = " ".join(p for p in (rec.failure.headline, rec.failure.advice) if p) \
                if rec.failure else ""
            title = "Job failed"
            message = f"{_subject(rec)} failed. {why}".strip()
    return Notification(event, title, message, rec)


class Channel(Protocol):
    name: str

    def send(self, note: Notification) -> None:
        """Deliver it, or raise."""


# Discord embed colours / ntfy tags+priority per event.
_COLOUR = {Event.RIP_DONE: 0x2E7D32, Event.REVIEW_NEEDED: 0xF9A825, Event.JOB_ARCHIVED: 0x1565C0,
           Event.JOB_FAILED: 0xC62828}
_TAGS = {Event.RIP_DONE: "white_check_mark", Event.REVIEW_NEEDED: "eyes",
         Event.JOB_ARCHIVED: "file_folder", Event.JOB_FAILED: "warning"}
_PRIORITY = {Event.RIP_DONE: 3, Event.REVIEW_NEEDED: 4, Event.JOB_ARCHIVED: 3, Event.JOB_FAILED: 4}


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


TEST = "test"
VERSION = 1


def ui_address(web: WebConfig) -> str:
    """Where another machine opens AMA's UI: this PC's name when it listens on every address."""
    host = socket.gethostname() if web.host in ("0.0.0.0", "::", "") else web.host
    if ":" in host:  # an IPv6 literal
        host = f"[{host}]"
    return f"http://{host}:{web.port}"


@dataclass
class Webhook:
    http: httpx.Client
    url: str
    ui: str  # ui_address(), for each Job's link
    header: tuple[str, str] | None = None
    name: str = "Webhook"

    def payload(self, event: str, at: datetime, rec: JobRecord | None) -> dict:
        return {"version": VERSION, "event": event,
                "at": at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "job": None if rec is None else {
                    "id": rec.id, "disc_type": rec.disc_type.value.lower(),
                    "title": rec.title or rec.name, "status": rec.status.value,
                    "url": f"{self.ui}/jobs/{rec.id}"}}

    def _post(self, body: dict) -> None:
        self.http.post(self.url, timeout=TIMEOUT, json=body,
                       headers=dict([self.header]) if self.header else None).raise_for_status()

    def send(self, note: Notification) -> None:
        self._post(self.payload(note.event, note.at, note.job))

    def send_test(self) -> str | None:
        """Post a "test" event: None if it went through, else why not (without secrets)."""
        try:
            self._post(self.payload(TEST, datetime.now(UTC), None))
        except Exception as e:  # noqa: BLE001 - reported on the page, not raised
            return _why(e)
        return None


def webhook(cfg: Config, http: httpx.Client) -> Webhook | None:
    w = cfg.webhook
    if not w.url:
        return None
    header = (w.header_name, w.header_value) if w.header_name and w.header_value else None
    return Webhook(http, w.url, ui_address(cfg.web), header)


def channels(cfg: Config, http: httpx.Client) -> list[Channel]:
    """The configured channels; one without its config value is simply not there."""
    out: list[Channel] = []
    if cfg.discord.webhook_url:
        out.append(Discord(http, cfg.discord.webhook_url))
    if cfg.ntfy.topic:
        out.append(Ntfy(http, cfg.ntfy.url, cfg.ntfy.topic))
    if hook := webhook(cfg, http):
        out.append(hook)
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
                    and rec.failure.kind in USER_STOPPED:
                continue  # the user's own decision
            if rec.all_skipped:
                continue  # the user's own decision during the Rip: nothing to go back for
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
