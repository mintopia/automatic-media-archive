"""The current Rip, whatever its Disc Type: one view the Now drive card and Ripping bin share.

Both read `current_rip(services)` (in `view_context` as `current_rip`), so they
can't disagree about whether a Rip is under way, its Phase or its progress.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ama.cdrip import CdRip
from ama.jobs import JobRecord
from ama.drive import DiscType
from ama.phase import Phase
from ama.video_rip import RipProgress

if TYPE_CHECKING:
    from ama.app import Services
    from ama.media import Screen


@dataclass(frozen=True)
class CurrentRip:
    disc_type: DiscType
    name: str             # the likely album/film once guessed, else the Disc's label
    detail: str           # sub-detail of the Phase: "Starting", "Track 2 of 12", "Title 3 of 7"
    percent: int | None   # whole Disc; None before there's anything to measure
    href: str | None      # where its live page is
    likely: bool = False  # `name` is a guess, only for show
    cover: str | None = None  # a guessed album's cached cover (CD)
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
        return _video(video.active, video.progress, video.likely)
    return None


def _cd(rip: CdRip) -> CurrentRip:
    g = rip.guess
    return CurrentRip(DiscType.CD, g.match.release.title if g else (rip.label or "Unknown CD"),
                      rip.position(), int(rip.percent), f"/jobs/{rip.job_id}",
                      likely=g is not None, cover=g.cover if g else None, cd=rip)


def _video(job: JobRecord, progress: RipProgress, likely: Screen | None) -> CurrentRip:
    detail = (f"Title {progress.title_number} of {len(job.titles)}" if progress.title_number
              else "Reading the Disc")
    return CurrentRip(job.disc_type, likely.name if likely else job.name, detail,
                      progress.pct, "/disc", likely=likely is not None, job=job,
                      progress=progress)
