"""TV Episode mapping, end to end: the real app with fakes for ffmpeg, the NAS folder
and the web (TMDB, Plex).

The TV Disc is put straight into scratch as ripped (the fake makemkvcon only knows a
film's Blu-ray): "THE_OFFICE_S1_D2", a DVD with three episodes (Titles 1-3), a
"Play all" of them (Title 4) and a 3-minute extra (Title 5).
"""

from __future__ import annotations

import html

from ama.archive import extended_path
from ama.discs import DiscStatus, ReviewReason, TitleRecord, TitleStatus
from ama.drive import DiscType
from tests.conftest import eventually

LABEL = "THE_OFFICE_S1_D2"
OFFICE = 2996
SHOW = "TV/The Office (2001) {tmdb-2996}"
TITLES = [(1, 29 * 60 + 10, "1"), (2, 29 * 60 + 40, "2"), (3, 30 * 60 + 5, "3"),
          (4, 88 * 60 + 55, "1,2,3"), (5, 3 * 60, "7")]


def _tv_disc(harness, label: str = LABEL, titles=TITLES, disc_type=DiscType.DVD):
    discs = harness.services.discs
    rec = discs.create(disc_type, label, "video")
    rec.scratch_dir.mkdir(parents=True)
    records = []
    for n, seconds, segments in titles:
        name = f"{label}_t{n - 1:02d}.mkv"
        (rec.scratch_dir / name).write_bytes(b"mkv")
        records.append(TitleRecord(n, n - 1, seconds, 1_000_000_000, 2, 1, segments, name,
                                   TitleStatus.RIPPED))
    discs.set_titles(rec.id, records, 0, 0)
    discs.mark_ripped(rec.id)
    return rec


def _the_office(harness) -> None:
    harness.web.add_series("THE OFFICE", OFFICE, "The Office", 2001, {
        1: [(1, "Downsize", 30), (2, "Work Experience", 29), (3, "The Quiz", 29),
            (4, "Training", 30), (5, "New Girl", 29), (6, "Judgement", 30)],
        2: [(1, "Merger", 29)],
        0: [(1, "Christmas Special (1)", 45), (2, "Christmas Special (2)", 45)]})


def _in_review(harness, rec):
    eventually(lambda: harness.services.discs.get(rec.id).status == DiscStatus.REVIEW, timeout=5)
    return harness.services.discs.get(rec.id)


def _page(client, url: str) -> str:
    r = client.get(url)
    assert r.status_code == 200, r.text
    return html.unescape(r.text)


def test_a_tv_disc_always_goes_to_review_even_when_a_film_matches(harness, client):
    # A film whose name and runtime fit the Disc's longest Title (the Play all).
    harness.web.add_film("THE OFFICE S1", 555, "The Office S1", runtime=89)
    rec = _in_review(harness, _tv_disc(harness))
    assert rec.review_reason == ReviewReason.EPISODES
    assert harness.services.movie_archive.movies.get(rec.id) is None
    assert harness.ffmpeg.encodes() == []
    queue = _page(client, "/review")
    assert "Looks like TV episodes" in queue and "Match episodes" in queue
