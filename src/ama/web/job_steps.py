"""A Job's Steps as its page lists them: Rip, Identification, one Encode per Title, File.

Each Step says whether it is done, running, waiting, failed or won't run, with its
timings; the Encode running now carries its live progress. Built from the stores
on every render (the page re-fetches it on each pipeline topic), never cached.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol

from ama import extras as extras_mod
from ama.phase import Phase, phase_of
from ama.jobs import JobRecord, JobStatus, FailureKind, LogLine
from ama.drive import DiscType
from ama.encode import EncodeProgress
from ama.encoder import EncodeStatus
from ama.web.review_items import reason_summary

if TYPE_CHECKING:
    from ama.app import Services


class StepState(StrEnum):
    DONE = "done"
    RUNNING = "running"
    WAITING = "waiting"
    FAILED = "failed"
    NOT_RUN = "notrun"  # an earlier Step failed: this one never will


@dataclass(frozen=True)
class Step:
    name: str          # "Rip" | "Identification" | "Encode" | "File" (GLOSSARY: Step)
    state: StepState
    detail: str        # the line under the name
    subject: str = ""  # what it acts on: "Main Feature, Title 1", "Example Movie (2016)"
    started: datetime | None = None
    finished: datetime | None = None
    progress: EncodeProgress | None = None  # the Encode running now
    colour: str = ""   # "rip" | "enc": the Phase colour while running
    number: int | None = None  # an Encode's Title

    @property
    def key(self) -> str:
        """The Step's key in its Job's Run (runs.py), which holds its output."""
        if self.name == "Encode":
            return f"encode:{self.number}" if self.number is not None else "encode"
        return {"Rip": "rip", "Identification": "identify", "File": "file"}[self.name]

    def took(self, now: datetime) -> str:
        """How long it took, or has taken so far; "" when it hasn't started."""
        if self.started is None:
            return ""
        end = self.finished or now
        s = max(0, round((end - self.started).total_seconds()))
        if s < 60:
            return f"{s} s"
        m = round(s / 60)
        return f"{m // 60} h {m % 60} min" if m >= 60 else f"{m} min"


@dataclass(frozen=True)
class Section:
    """Where a Job's page sits, by its Phase: Now while active, Review, History once Filed."""

    label: str
    href: str


NOW = Section("Now", "/")
REVIEW = Section("Review", "/review")
HISTORY = Section("History", "/history")


def section(rec: JobRecord) -> Section:
    if rec.status == JobStatus.FILED:
        return HISTORY
    if rec.status == JobStatus.REVIEW:
        return REVIEW
    return NOW


_IDENTIFIED = ("Identified as ", "Review: ")


def _why(lines: list[LogLine]) -> LogLine | None:
    """The log line saying what the Job was identified as and how (the latest)."""
    return next((ln for ln in reversed(lines) if ln.text.startswith(_IDENTIFIED)
                 and not ln.text.startswith("Review: Rip discarded")), None)


class _StepLike(Protocol):
    name: str
    state: str


def job_phase(rec: JobRecord, steps: Sequence[_StepLike]) -> Phase:
    """The Job's Phase, from its status and its Steps (GLOSSARY: Phase).

    `ripped` spans more than one Phase: the Job is Ripping until it is identified, then
    Encoding while its Title Encodes (and the File after them) run. A CD has no Encode,
    so it stays Ripping until it is filed."""
    if rec.status == JobStatus.RIPPED and any(
            s.name == "Identification" and s.state == StepState.DONE for s in steps) \
            and any(s.name == "Encode" for s in steps):
        return Phase.ENCODING
    return phase_of(rec.status)


def phase_now(services: Services, rec: JobRecord) -> Phase:
    """`job_phase` from the Job's Steps as they stand now."""
    return job_phase(rec, job_steps(services, rec))


def job_steps(services: Services, rec: JobRecord) -> list[Step]:
    lines = services.jobs.log_lines(rec.id)
    rip = _rip(services, rec)
    ident = _identification(services, rec, rip, lines)
    encodes = [] if rec.disc_type == DiscType.CD else _encodes(services, rec, ident)
    return [rip, ident, *encodes, _file(rec, ident, encodes, services.archive.root)]


def _rip(services: Services, rec: JobRecord) -> Step:
    if rec.disc_type == DiscType.CD:
        cd = services.cd.job(rec.id)
        n = len(cd.tracks) if cd else 0
        what = f"{n} track{'s' if n != 1 else ''}"
    else:
        n = len(rec.titles)
        what = f"{n} Title{'s' if n != 1 else ''}, {rec.total_size}"
    times = {"started": rec.started_at, "finished": rec.finished_at}
    if rec.status == JobStatus.RIPPING:
        return Step("Rip", StepState.RUNNING, "Copying the Disc to scratch",
                    started=rec.started_at, colour="rip")
    if rec.status == JobStatus.FAILED and rec.failure is not None \
            and rec.failure.kind not in (FailureKind.DISCARDED, FailureKind.SCRATCH_CLEANED):
        return Step("Rip", StepState.FAILED, rec.failure.headline, **times)
    return Step("Rip", StepState.DONE, what, **times)


def _identified_as(services: Services, rec: JobRecord) -> str:
    """What a video Job was identified as, once it is; "" before."""
    movie = services.movie_archive.movies.get(rec.id)
    if movie is not None:
        return movie.film.name
    rows = services.tv_archive.titles.for_job(rec.id)
    if rows:
        series = rows[0].series.title
        return series if any(r.episode for r in rows) else f"Extras of {series}"
    return ""


def _identification(services: Services, rec: JobRecord, rip: Step,
                    lines: list[LogLine]) -> Step:
    name = "Identification"
    if rip.state in (StepState.RUNNING, StepState.FAILED):
        return Step(name, StepState.WAITING if rip.state == StepState.RUNNING
                    else StepState.NOT_RUN, "After the Rip")
    why = _why(lines)
    started = rec.finished_at
    if rec.status == JobStatus.FAILED and rec.scratch_cleaned_at is None:  # discarded in Review
        return Step(name, StepState.FAILED, "The Rip was discarded in Review", started=started)
    if rec.status == JobStatus.REVIEW:
        reason = reason_summary(rec.review_reason) if rec.review_reason else "Needs a decision"
        return Step(name, StepState.WAITING, f"Needs Review: {reason}", started=started)
    as_ = (rec.title if rec.status == JobStatus.FILED and rec.disc_type == DiscType.CD
           else "" if rec.disc_type == DiscType.CD else _identified_as(services, rec))
    if as_ or why is not None or rec.status == JobStatus.FILED:
        return Step(name, StepState.DONE, why.text if why else "", subject=as_ or rec.title,
                    started=started, finished=why.at if why else None)
    source = "MusicBrainz" if rec.disc_type == DiscType.CD else "TMDB"
    return Step(name, StepState.RUNNING, f"Looking it up on {source}", started=started)


_STATE = {EncodeStatus.QUEUED: StepState.WAITING, EncodeStatus.ENCODING: StepState.RUNNING,
          EncodeStatus.ENCODED: StepState.DONE, EncodeStatus.FILED: StepState.DONE,
          EncodeStatus.FAILED: StepState.FAILED}
_DETAIL = {EncodeStatus.QUEUED: "Waiting its turn", EncodeStatus.ENCODING: "Encoding",
           EncodeStatus.ENCODED: "Encoded · waiting to be filed", EncodeStatus.FILED: "Filed",
           EncodeStatus.FAILED: "The Encode didn't work · retried when the app restarts"}


def _extra(name: str, number: int) -> str:
    """"Extra: Trailer, Title 4"; an unnamed Extra ("LABEL - Title 4") says its Title once."""
    return f"Extra: {name}" + ("" if name.endswith(f"Title {number}") else f", Title {number}")


def _encodes(services: Services, rec: JobRecord, ident: Step) -> list[Step]:
    """One Encode Step per Title kept: (subject, status) from the film's or TV's queue."""
    planned: list[tuple[int, str, EncodeStatus | None, str]] = []  # number, subject, status, note
    movie = services.movie_archive.movies.get(rec.id)
    if movie is not None:
        planned.append((movie.title_number, f"Main Feature, Title {movie.title_number}",
                        movie.status, ""))
        main_failed = movie.status == EncodeStatus.FAILED
        named = {e.title_number: e for e in services.movie_archive.extras.of(rec.id)}
        for t in extras_mod.extra_titles(rec.titles, movie.title_number):
            e = named.get(t.number)
            if e is not None:
                planned.append((t.number, _extra(e.name, t.number), e.status,
                                "The Extra is left out" if e.status == EncodeStatus.FAILED
                                else ""))
            else:
                planned.append((t.number, f"Extra, Title {t.number}", None,
                                "Not run: the Main Feature's Encode didn't work" if main_failed
                                else "Starts when the Main Feature is done"))
    for row in services.tv_archive.titles.for_job(rec.id):
        ep = row.episode
        what = (f"Episode {ep.code} · {ep.name}" if ep.name else f"Episode {ep.code}") if ep \
            else None
        planned.append((row.title_number, f"{what}, Title {row.title_number}" if what
                        else _extra(row.path.stem, row.title_number), row.status, ""))
    if not planned:
        state = StepState.NOT_RUN if ident.state in (StepState.FAILED, StepState.NOT_RUN) \
            else StepState.WAITING
        return [Step("Encode", state, "One per Title kept, once it is identified")]
    encode = services.movie_archive.encoder.current
    times = services.jobs.encode_times(rec.id)
    steps = []
    for number, subject, status, note in planned:
        started, finished = times.get(number, (None, None))
        if status is None:
            steps.append(Step("Encode", StepState.NOT_RUN if note.startswith("Not run")
                              else StepState.WAITING, note, subject, number=number))
            continue
        if rec.status == JobStatus.FILED and status == EncodeStatus.ENCODED:
            status = EncodeStatus.FILED  # a film's row stays "encoded" once it is filed
        live = encode is not None and encode.job.id == rec.id and encode.title_number == number
        state = StepState.RUNNING if live else _STATE[status]
        if rec.status == JobStatus.FILED and state == StepState.WAITING:
            state = StepState.NOT_RUN
        detail = note or _DETAIL[EncodeStatus.ENCODING if live else status]
        if rec.status == JobStatus.FAILED and status == EncodeStatus.FAILED:
            detail = "The Encode didn't work"  # no retry: its Rip is gone
        steps.append(Step("Encode", state, detail, subject,
                          started=started, finished=finished if state != StepState.RUNNING
                          else None, progress=encode.progress if live else None, colour="enc",
                          number=number))
    return steps


def _file(rec: JobRecord, ident: Step, encodes: list[Step], root: Path) -> Step:
    if rec.status == JobStatus.FILED:
        where = "the Archive"
        if rec.archive_dir is not None:
            try:
                where = rec.archive_dir.relative_to(root).as_posix()
            except ValueError:
                where = str(rec.archive_dir)
        before = [s.finished for s in (ident, *encodes) if s.finished]
        return Step("File", StepState.DONE, f"Filed to {where}",
                    started=max(before) if before else None, finished=rec.filed_at)
    if rec.status == JobStatus.FAILED:
        return Step("File", StepState.NOT_RUN, "Not filed")
    ready = ident.state == StepState.DONE and all(
        s.state in (StepState.DONE, StepState.FAILED, StepState.NOT_RUN) for s in encodes)
    if ready:
        return Step("File", StepState.RUNNING, "Filing to the NAS, then a Plex scan")
    return Step("File", StepState.WAITING, "To the NAS, then a Plex scan")
