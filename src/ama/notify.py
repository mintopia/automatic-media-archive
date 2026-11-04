"""Push notifications to Discord (webhook) and ntfy (topic) that pull people back to the UI.

Three events, read off Disc status changes (`DiscStore.statuses()`) whenever
anything is published on the bus, so no pipeline stage has to call this:

- Disc done: a Disc's Rip finished and it was ejected (left `ripping` for
  `ripped`/`review`/`filed`), so the next Disc can go in.
- Review needed: a Disc entered `review`.
- Disc failed: a Disc became `failed` (not when the user discarded it in Review).

A channel is on when its config value is set (`discord.webhook_url`,
`ntfy.topic`), else silently absent. Sending happens on a worker thread from
the notifier's own task, and every failure is logged and dropped: a
notification never blocks or breaks the pipeline. Discs already in a state at
startup don't notify again. Log lines never contain the webhook URL or topic
(both are secrets).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

import httpx

from ama.config import Config
from ama.discs import DiscRecord, DiscStatus, DiscStore, FailureKind
from ama.events import EventBus

log = logging.getLogger(__name__)


class Event(StrEnum):
    DISC_DONE = "disc_done"
    REVIEW_NEEDED = "review_needed"
    DISC_FAILED = "disc_failed"


_DONE = {DiscStatus.RIPPED, DiscStatus.REVIEW, DiscStatus.FILED}


def changes(before: Mapping[int, DiscStatus],
            after: Mapping[int, DiscStatus]) -> list[tuple[int, Event]]:
    """The events between two `statuses()` snapshots, oldest Disc first."""
    out: list[tuple[int, Event]] = []
    for disc_id in sorted(after):
        prev, cur = before.get(disc_id), after[disc_id]
        if prev == cur:
            continue
        if prev in (None, DiscStatus.RIPPING) and cur in _DONE:
            out.append((disc_id, Event.DISC_DONE))
        if cur == DiscStatus.REVIEW:
            out.append((disc_id, Event.REVIEW_NEEDED))
        if cur == DiscStatus.FAILED:
            out.append((disc_id, Event.DISC_FAILED))
    return out


@dataclass(frozen=True)
class Notification:
    event: Event
    title: str
    message: str


def _subject(rec: DiscRecord) -> str:
    return f"{rec.disc_type.long_name} “{rec.label}”" if rec.label else rec.disc_type.long_name


def notification(event: Event, rec: DiscRecord) -> Notification:
    match event:
        case Event.DISC_DONE:
            return Notification(event, "Disc done · insert the next one",
                                f"{_subject(rec)} is ripped and ejected. Insert the next Disc.")
        case Event.REVIEW_NEEDED:
            return Notification(event, "Review needed",
                                f"{_subject(rec)} needs Review before it can be filed.")
        case Event.DISC_FAILED:
            why = " ".join(p for p in (rec.failure.headline, rec.failure.advice) if p) \
                if rec.failure else ""
            return Notification(event, "Disc failed", f"{_subject(rec)} failed. {why}".strip())


class Channel(Protocol):
    name: str

    def send(self, note: Notification) -> None:
        """Deliver it, or raise."""


# Discord embed colours / ntfy tags+priority per event.
_COLOUR = {Event.DISC_DONE: 0x2E7D32, Event.REVIEW_NEEDED: 0xF9A825, Event.DISC_FAILED: 0xC62828}
_TAGS = {Event.DISC_DONE: "white_check_mark", Event.REVIEW_NEEDED: "eyes",
         Event.DISC_FAILED: "warning"}
_PRIORITY = {Event.DISC_DONE: 3, Event.REVIEW_NEEDED: 4, Event.DISC_FAILED: 4}


@dataclass
class Discord:
    http: httpx.Client
    webhook_url: str
    name: str = "Discord"

    def send(self, note: Notification) -> None:
        # wait=true: otherwise a message Discord drops still answers 204.
        self.http.post(self.webhook_url, params={"wait": "true"}, json={
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
        self.http.post(self.url.rstrip("/") + "/", json={
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


class Notifier:
    """Background task: watches Disc statuses after every bus event and notifies."""

    def __init__(self, discs: DiscStore, bus: EventBus, channels: Sequence[Channel]) -> None:
        self._discs = discs
        self._bus = bus
        self.channels = list(channels)

    def send(self, notes: Sequence[Notification]) -> None:
        """Every note to every channel; failures are logged, never raised."""
        for note in notes:
            for ch in self.channels:
                try:
                    ch.send(note)
                except Exception as e:  # noqa: BLE001 - nothing here may break the pipeline
                    log.warning("Couldn't send the %s notification to %s: %s",
                                note.title, ch.name, _why(e))

    def _notes(self, events: list[tuple[int, Event]]) -> list[Notification]:
        notes = []
        for disc_id, event in events:
            rec = self._discs.get(disc_id)
            if rec is None:
                continue
            if event == Event.DISC_FAILED and rec.failure \
                    and rec.failure.kind == FailureKind.DISCARDED:
                continue  # the user's own decision in Review
            notes.append(notification(event, rec))
        return notes

    async def run(self) -> None:
        if not self.channels:
            return
        with self._bus.subscribe() as topics:
            seen = self._discs.statuses()
            while True:
                await topics.get()
                while not topics.empty():  # one look covers a burst of events
                    topics.get_nowait()
                try:
                    now = self._discs.statuses()
                    notes = self._notes(changes(seen, now))
                    seen = now
                except Exception:  # noqa: BLE001
                    log.exception("Couldn't check Discs for notifications")
                    continue
                if notes:
                    await asyncio.to_thread(self.send, notes)
