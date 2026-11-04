"""The Review queue, shared by every Disc Type: Discs whose Identification needs a human.

A Disc is in the queue while its status is `review` (`DiscRecord.review_reason`
says why). Whoever changes the queue publishes `TOPIC`. Each Disc Type has its
own Review page and decision (CD: `cdreview`); once decided, the Disc goes back
to `ripped` (`DiscStore.requeue`) and its stage worker files it.
"""

from __future__ import annotations

from ama.discs import DiscRecord, DiscStatus, DiscStore

TOPIC = "review"


def queue(discs: DiscStore) -> list[DiscRecord]:
    """Discs waiting for Review, oldest first."""
    return list(reversed(discs.list(DiscStatus.REVIEW)))
