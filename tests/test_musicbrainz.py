"""Identification: which release (and which of its discs) a MusicBrainz Disc ID response names.

Tested against the real response for the FFVII Rebirth OST disc 1 (tests/data/README.md).
"""

from __future__ import annotations

import json

from ama import musicbrainz
from tests.fakes import DATA

DISC_1 = "kIBdaUqY_5kMBgOXehaFmL5TSbA-"
DISC_2 = "O75dAncJZ7onpacHCAgF4NqupdA-"


def _response() -> dict:
    return json.loads((DATA / "musicbrainz" / "discid-ffvii-rebirth-disc1.json")
                      .read_text(encoding="utf-8"))


def test_every_release_containing_the_disc_is_a_match():
    matches = musicbrainz.matches(_response(), DISC_1)
    assert [(m.release.id, m.disc_number, m.release.disc_total) for m in matches] == [
        ("139f3172-07da-488b-a4f2-3c6162a2f7cd", 1, 8),
        ("5afc3090-044d-4f34-a188-a273b8cf6e0e", 1, 8),
        ("b543589a-95c2-4c29-ba33-f9137ff8eb4c", 1, 7),
    ]


def test_a_match_carries_what_tagging_and_archiving_need():
    m = musicbrainz.matches(_response(), DISC_1)[0]
    r = m.release
    assert r.title == "FINAL FANTASY VII REBIRTH Original Soundtrack ～Special edit version～"
    assert r.artist == "Various Artists"
    assert r.is_compilation
    assert (r.date, r.country, r.barcode) == ("2024-04-10", "JP", "4988601470865")
    assert len(m.tracks) == 24
    first = m.tracks[0]
    assert (first.number, first.title) == (1, "The Unknown Journey Continues")
    assert first.artist == "島翔太朗 & 西木康智"
    assert first.artist_ids == ("e9235369-ddb5-4418-bd98-48af40d6b782",
                                "181c4177-f33a-441d-b15d-910acaf18b07")
    assert first.recording_id == "000e6813-b15d-405d-83ea-7b56b431dca0"
    assert first.track_id == "bb88f3d1-6d30-4200-bb45-7a15792e54b9"


def test_the_disc_number_comes_from_the_medium_holding_the_disc_id():
    matches = musicbrainz.matches(_response(), DISC_2)
    assert [(m.disc_number, len(m.tracks)) for m in matches] == [(2, 23)] * 3


def test_a_disc_id_on_no_medium_matches_nothing():
    assert musicbrainz.matches(_response(), "x" * 27 + "-") == []


def test_the_user_agent_gives_musicbrainz_the_projects_github_home():
    # MusicBrainz asks every client to say who it is and where to reach it.
    assert musicbrainz.USER_AGENT.startswith("AMA/")
    assert musicbrainz.USER_AGENT.endswith(
        "( https://github.com/mintopia/automatic-media-archive )")
