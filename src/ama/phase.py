"""The Phase: the single user-facing stage a Job is in (GLOSSARY.md).

Every status the UI shows is a `Phase`; finer internal states (a Job's
`JobStatus`, an Encode's status) display as the Phase they belong to.
"""

from __future__ import annotations

from enum import StrEnum

from ama.jobs import JobStatus


class Phase(StrEnum):
    RIPPING = "Ripping"
    REVIEW = "Review"
    ENCODING = "Encoding"
    ARCHIVED = "Archived"
    FAILED = "Failed"

    @property
    def css(self) -> str:
        """The status chip's class (`stk <css>`, DESIGN.md)."""
        return _CSS[self]


_CSS = {Phase.RIPPING: "rip", Phase.REVIEW: "rev", Phase.ENCODING: "enc",
        Phase.ARCHIVED: "arc", Phase.FAILED: "fail"}

# `ripped` = waiting for Identification, which is still part of Ripping on the Now page.
_OF_STATUS = {JobStatus.RIPPING: Phase.RIPPING, JobStatus.RIPPED: Phase.RIPPING,
              JobStatus.REVIEW: Phase.REVIEW, JobStatus.ARCHIVED: Phase.ARCHIVED,
              JobStatus.FAILED: Phase.FAILED}


def phase_of(status: JobStatus | str) -> Phase:
    return _OF_STATUS[JobStatus(status)]
