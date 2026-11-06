"""The Review queue, shared by every Disc Type: Discs whose Identification needs a human.

A Disc is in the queue while its status is `review` (`JobRecord.review_reason`
says why). Whoever changes the queue publishes `Topic.REVIEW`. Each Disc Type has its
own Review page and decision (CD: `cdreview`); once decided, the Disc goes back
to `ripped` (`JobStore.requeue`) and its stage worker archives it.
"""

from __future__ import annotations

from ama.jobs import JobRecord, JobStatus, JobStore


def queue(jobs: JobStore) -> list[JobRecord]:
    """Discs waiting for Review, oldest first."""
    return list(reversed(jobs.list(JobStatus.REVIEW)))
