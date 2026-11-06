"""The current Rip, whatever its Disc Type: one view the Now drive card and Ripping bin share.

Both read `current_rip(services)` (in `view_context` as `current_rip`), so they
can't disagree about whether a Rip is under way, its Phase or its progress.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ama import tvreview
from ama.cdrip import CdRip
from ama.jobs import JobRecord
from ama.drive import DiscType
from ama.phase import Phase
from ama.video_rip import RipProgress

if TYPE_CHECKING:
    from ama.app import Services
    from ama.film_guess import FilmGuess
    from ama.series_guess import SeriesGuess


@dataclass(frozen=True)
class CurrentRip:
    disc_type: DiscType
    name: str             # the likely album/film once guessed, else the Disc's label
    detail: str           # sub-detail of the Phase: "Starting", "Track 2 of 12", "Title 3 of 7"
    percent: int | None   # whole Disc; None before there's anything to measure
    href: str | None      # where its live page is
    likely: bool = False  # `name` is a guess (a CD's likely album, a video Best guess)
    picked: bool = False  # `name` is the release the user picked (CD)
    cover: str | None = None  # a guessed album's cover or film's poster, cached
    phase: Phase = Phase.RIPPING
    # The source state, for the drive card's full detail.
    cd: CdRip | None = None
    job: JobRecord | None = None
    progress: RipProgress | None = None


def current_rip(services: Services) -> CurrentRip | None:
    cd = services.cd
    if cd.current is not None:
        return _cd(cd.current)
    if cd.reading_toc:
        return CurrentRip(DiscType.CD, DiscType.CD.long_name, "Starting", None, None)
    video = services.video_rip
    if video.active is not None and video.progress is not None:
        job = video.active
        guesses = services.series_guesses if tvreview.marked(job) else services.film_guesses
        return _video(job, video.progress, guesses.get(job.id))
    return None


def _cd(rip: CdRip) -> CurrentRip:
    g = rip.guess
    return CurrentRip(DiscType.CD, g.title if g else (rip.label or "Unknown CD"),
                      rip.position(), int(rip.percent), f"/jobs/{rip.job_id}",
                      likely=g is not None and not g.picked, picked=g is not None and g.picked,
                      cover=g.cover if g else None, cd=rip)


def _video(job: JobRecord, progress: RipProgress,
           guess: FilmGuess | SeriesGuess | None) -> CurrentRip:
    detail = (f"Title {progress.title_number} of {len(job.titles)}" if progress.title_number
              else "Reading the Disc")
    return CurrentRip(job.disc_type, guess.name if guess else job.name, detail,
                      progress.pct, f"/jobs/{job.id}", likely=guess is not None,
                      cover=guess.poster if guess else None, job=job, progress=progress)
