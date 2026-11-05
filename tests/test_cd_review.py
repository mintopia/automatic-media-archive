"""CD Review, end to end: the real app with a fake drive, cyanrip, NAS folder and web.

The FFVII Rebirth OST disc 1 capture has 3 MusicBrainz releases, so it lands in
Review; the user picks one (or enters the details) and it is filed.
"""

from __future__ import annotations

import html

from mutagen.flac import FLAC

from ama.archive import extended_path
from ama.jobs import JobStatus, ReviewReason
from ama.drive import DiscType
from tests.conftest import eventually
from tests.test_cd_archive import ALBUM, COVER, DISC_1, SPECIAL, _album, _insert, _response, _wait_for

STANDARD = "b543589a-95c2-4c29-ba33-f9137ff8eb4c"  # the 7-CD edition
PSEUDO = "5afc3090-044d-4f34-a188-a273b8cf6e0e"


def _page(client, url: str) -> str:
    r = client.get(url)
    assert r.status_code == 200, r.text
    return html.unescape(r.text)


def test_the_review_queue_lists_pending_discs_with_why(harness, client):
    _insert(harness, DISC_1, 24, _response())
    rec = _wait_for(harness, JobStatus.REVIEW)

    for url in ("/", "/review"):
        page = _page(client, url)
        assert 'Needs Review <span class="c">1</span>' in page
        assert "3 editions match this CD" in page
        assert f'href="/review/{rec.id}"' in page
        assert "Choose edition" in page
    assert '<span class="count" aria-hidden="true">1</span><span class="sr">, 1 waiting</span>' in _page(client, "/")


def test_an_empty_review_queue_says_so(client):
    assert "Nothing needs you right now" in _page(client, "/review")
    assert 'class="count"' not in _page(client, "/")


def test_the_review_page_shows_what_tells_the_editions_apart(harness, client):
    _insert(harness, DISC_1, 24, _response())
    rec = _wait_for(harness, JobStatus.REVIEW)

    page = _page(client, f"/review/{rec.id}")
    assert f"Which edition of {ALBUM} is this?" in page
    assert "3 editions match this CD" in page
    assert "4988601470865" in page and "4988601470872" in page   # barcodes
    assert "Japan · 2024-04-10" in page
    assert "8 CDs" in page and "7 CDs" in page
    assert "Pseudo-Release" in page
    assert DISC_1[:10] in page                                  # This CD: Disc ID
    assert f'value="{STANDARD}:1"' in page
    assert "couldn't be verified" not in page   # all tracks verified: no AccurateRip notice


def _edition_block(page: str, release_id: str) -> str:
    start = page.index(f'value="{release_id}:1"')
    end = page.find('<label class="radio"', start)
    return page[start:end if end != -1 else len(page)]


def test_each_edition_previews_its_track_list_and_the_title_differences_show(harness, client):
    harness.web.covers[SPECIAL] = COVER
    _insert(harness, DISC_1, 24, _response())
    rec = _wait_for(harness, JobStatus.REVIEW)
    requests_before = len(harness.web.requests)

    page = _page(client, f"/review/{rec.id}")
    english = _edition_block(page, PSEUDO)
    japanese = _edition_block(page, STANDARD)
    assert "English track titles" in english                      # MusicBrainz disambiguation
    assert "Another Buster Sword" in english and "もうひとつのバスターソード" not in english
    assert "もうひとつのバスターソード" in japanese and "Another Buster Sword" not in japanese
    for block in (english, japanese):
        assert "The Unknown Journey Continues" in block and "2:00" in block   # title, length
        assert block.count('<tr') >= 24
    assert "Shotaro Shima" in english and "島翔太朗" in japanese   # track artists (Various Artists)
    # Track 1 is the same in every edition; track 2's title differs, and is marked.
    assert '<td class="diff">Another Buster Sword<' in english
    assert '<td class="diff">The Unknown Journey Continues' not in english
    # The two Japanese editions agree, so it's the English one whose titles stand out.
    assert 'class="diff"' not in japanese and "differ from the other editions" not in japanese
    assert "23 titles differ from the other editions" in english
    # Covers come from the Cover Art Archive (cached), not another MusicBrainz call.
    assert f"/review/{rec.id}/cover/{SPECIAL}" in _edition_block(page, SPECIAL)
    assert client.get(f"/review/{rec.id}/cover/{SPECIAL}").content == COVER
    assert client.get(f"/review/{rec.id}/cover/not-a-candidate").status_code == 404
    assert not any(r.url.host == "musicbrainz.org" for r in harness.web.requests[requests_before:])


def test_picking_an_edition_files_the_cd(harness, client):
    harness.web.covers[STANDARD] = COVER
    _insert(harness, DISC_1, 24, _response())
    rec = _wait_for(harness, JobStatus.REVIEW)

    r = client.post(f"/review/{rec.id}/release", data={"release": f"{STANDARD}:1"},
                    follow_redirects=False)
    assert r.status_code == 303

    filed = _wait_for(harness, JobStatus.FILED)
    album = extended_path(harness.nas_root / "Music" / "Various Artists"
                          / "FINAL FANTASY VII REBIRTH Original Soundtrack")
    flacs = sorted(p.name for p in album.iterdir() if p.name.endswith(".flac"))
    assert len(flacs) == 24
    tags = FLAC(album / flacs[0])
    assert tags["MUSICBRAINZ_ALBUMID"] == [STANDARD]
    assert (tags["DISCNUMBER"], tags["DISCTOTAL"]) == (["1"], ["7"])
    assert (album / "cover.jpg").read_bytes() == COVER
    assert filed.title == "FINAL FANTASY VII REBIRTH Original Soundtrack — Various Artists"
    assert "Nothing needs you right now" in _page(client, "/review")


def test_picking_an_edition_waits_for_the_nas_like_automatic_filing(harness, client):
    harness.share["reachable"] = False
    _insert(harness, DISC_1, 24, _response())
    rec = _wait_for(harness, JobStatus.REVIEW)
    client.post(f"/review/{rec.id}/release", data={"release": f"{SPECIAL}:1"})
    eventually(lambda: any("NAS" in ln.text for ln in harness.services.jobs.log_lines(rec.id)))
    assert harness.services.jobs.get(rec.id).status == JobStatus.RIPPED
    harness.share["reachable"] = True
    _wait_for(harness, JobStatus.FILED)
    assert (_album(harness)).exists()


def test_an_edition_that_isnt_offered_is_refused(harness, client):
    _insert(harness, DISC_1, 24, _response())
    rec = _wait_for(harness, JobStatus.REVIEW)
    r = client.post(f"/review/{rec.id}/release", data={"release": "nope:1"})
    assert r.status_code == 400
    assert harness.services.jobs.get(rec.id).status == JobStatus.REVIEW


def test_a_disc_musicbrainz_doesnt_know_is_filed_from_details_entered_by_hand(harness, client):
    _insert(harness, DISC_1, 3, 404)
    rec = _wait_for(harness, JobStatus.REVIEW)
    assert rec.review_reason == ReviewReason.NO_RELEASE

    page = _page(client, f"/review/{rec.id}")
    assert "This CD has 3 tracks" in page
    assert "<details class=\"manual\" open>" in page

    r = client.post(f"/review/{rec.id}/manual", data={
        "album": "Kid A", "artist": "Radiohead", "year": "2000",
        "tracks": "Everything in Its Right Place\r\nKid A\r\n\r\nThe National Anthem\r\n"},
        follow_redirects=False)
    assert r.status_code == 303

    filed = _wait_for(harness, JobStatus.FILED)
    album = extended_path(harness.nas_root / "Music" / "Radiohead" / "Kid A")
    names = sorted(p.name for p in album.iterdir())
    assert names == ["01 - Everything in Its Right Place.flac", "02 - Kid A.flac",
                     "03 - The National Anthem.flac", "Kid A.cue", "Kid A.log"]
    tags = FLAC(album / names[1])
    assert tags["TITLE"] == ["Kid A"] and tags["ARTIST"] == ["Radiohead"]
    assert tags["ALBUM"] == ["Kid A"] and tags["DATE"] == ["2000"]
    assert tags["MUSICBRAINZ_DISCID"] == [DISC_1]
    assert "MUSICBRAINZ_ALBUMID" not in tags and "MUSICBRAINZ_TRACKID" not in tags
    assert filed.title == "Kid A — Radiohead"
    assert not any("coverartarchive" in str(r.url) for r in harness.web.requests)


def test_manual_details_must_name_every_track(harness, client):
    _insert(harness, DISC_1, 3, 404)
    rec = _wait_for(harness, JobStatus.REVIEW)
    r = client.post(f"/review/{rec.id}/manual", data={
        "album": "Kid A", "artist": "", "year": "two thousand", "tracks": "One\nTwo"})
    assert r.status_code == 400
    page = html.unescape(r.text)
    assert "Enter the artist" in page
    assert "This CD has 3 tracks, but you entered 2 titles" in page
    assert "Enter the year as four digits" in page
    assert 'value="Kid A"' in page   # what was typed is kept
    assert harness.services.jobs.get(rec.id).status == JobStatus.REVIEW


def test_manual_entry_is_prefilled_from_an_edition_when_there_is_one(harness, client):
    _insert(harness, DISC_1, 24, _response())
    rec = _wait_for(harness, JobStatus.REVIEW)
    page = _page(client, f"/review/{rec.id}")
    assert "None of these: enter the details myself" in page
    assert "The Unknown Journey Continues" in page.split('id="tracks"')[1]


def _mismatch(harness, response, bad=(4, 9)):
    harness.web.musicbrainz[DISC_1] = response
    harness.cyanrip.mb_disc_id = DISC_1
    harness.cyanrip.tracks = [(n, 120.0) for n in range(1, 25)]
    harness.cyanrip.ar_confidence = {n: 65 for n in range(1, 25) if n not in bad}
    harness.drive.insert(DiscType.CD)
    return _wait_for(harness, JobStatus.REVIEW)


def test_tracks_accuraterip_didnt_verify_are_clearly_shown(harness, client):
    rec = _mismatch(harness, _response(only=SPECIAL))
    assert "2 tracks didn't match" in _page(client, "/")
    page = _page(client, f"/review/{rec.id}")
    assert "2 tracks don't match other people's copies of this CD" in page
    assert "Tracks 4 and 9 sound different from copies others have ripped (checked with "         "AccurateRip)" in page
    assert "Keep these tracks" in page and "Discard and re-rip" in page
    assert 'role="alertdialog"' in page and "Discard this Rip?" in page  # asked before deleting


def test_accepting_an_unverified_rip_with_one_edition_files_it(harness, client):
    rec = _mismatch(harness, _response(only=SPECIAL))
    r = client.post(f"/review/{rec.id}/accept", follow_redirects=False)
    assert r.status_code == 303
    _wait_for(harness, JobStatus.FILED)
    assert _album(harness).exists()
    assert any("accepted" in ln.text.lower() for ln in harness.services.jobs.log_lines(rec.id))
    history = _page(client, "/history")
    assert "accepted with 2 tracks not matching" in history and "verified" not in history


def test_history_says_when_a_filed_cd_was_not_in_accuraterip(harness, client):
    harness.cyanrip.in_accuraterip = False
    _insert(harness, DISC_1, 24, _response(only=SPECIAL))
    rec = _wait_for(harness, JobStatus.REVIEW)
    client.post(f"/review/{rec.id}/accept")
    _wait_for(harness, JobStatus.FILED)
    assert "24 tracks · not in AccurateRip" in _page(client, "/history")


def test_accepting_an_unverified_rip_with_several_editions_then_asks_which(harness, client):
    rec = _mismatch(harness, _response())
    client.post(f"/review/{rec.id}/accept")
    eventually(lambda: harness.services.jobs.get(rec.id).review_reason
               == ReviewReason.MULTIPLE_RELEASES)
    page = _page(client, f"/review/{rec.id}")
    assert "couldn't be verified" not in page
    assert "Which edition of" in page


def test_discarding_an_unverified_rip_deletes_it(harness, client):
    rec = _mismatch(harness, _response(only=SPECIAL))
    r = client.post(f"/review/{rec.id}/discard", follow_redirects=False)
    assert r.status_code == 303
    after = harness.services.jobs.get(rec.id)
    assert after.status == JobStatus.FAILED and after.dismissed
    assert not rec.scratch_dir.exists()
    assert not (harness.nas_root / "Music").exists()
    page = _page(client, "/")
    assert "Didn't work" not in page or f"/jobs/{rec.id}" not in page
    assert 'Needs Review <span class="c">0</span>' in page


def test_a_cd_not_in_accuraterip_explains_it_cant_be_verified(harness, client):
    harness.cyanrip.in_accuraterip = False
    _insert(harness, DISC_1, 24, _response(only=SPECIAL))
    rec = _wait_for(harness, JobStatus.REVIEW)
    page = _page(client, f"/review/{rec.id}")
    assert "This CD isn't in the online check (AccurateRip)" in page
    assert "Keep this Rip" in page


def test_a_decision_on_a_disc_no_longer_in_review_is_ignored(harness, client):
    _insert(harness, DISC_1, 24, _response())
    rec = _wait_for(harness, JobStatus.REVIEW)
    client.post(f"/review/{rec.id}/release", data={"release": f"{STANDARD}:1"})
    _wait_for(harness, JobStatus.FILED)
    r = client.post(f"/review/{rec.id}/release", data={"release": f"{SPECIAL}:1"},
                    follow_redirects=False)
    assert r.status_code == 303
    assert harness.services.jobs.get(rec.id).title.startswith(
        "FINAL FANTASY VII REBIRTH Original Soundtrack —")
    assert client.get(f"/review/{rec.id}", follow_redirects=False).status_code == 303
