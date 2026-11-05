"""Movie Identification's pure parts: search terms from the Disc, and when a TMDB
match is confident enough to accept with no human."""

from __future__ import annotations

from pathlib import Path

from ama.jobs import ReviewReason
from ama.tmdb import Candidate, DiscHints, bd_meta_title, decide, movie_folder, search_terms


def test_search_terms_come_from_bd_metadata_makemkv_name_and_volume_label_cleaned_up():
    hints = DiscHints(volume_label="ARRIVAL_DISC1", disc_name="Arrival",
                      bd_title="Arrival", volume_name="ARRIVAL_DISC1")
    assert search_terms(hints) == ["Arrival"]
    hints = DiscHints(volume_label="BLADE_RUNNER_2049_BD", disc_name="BLADE_RUNNER_2049_BD")
    assert search_terms(hints) == ["BLADE RUNNER 2049"]
    hints = DiscHints(volume_label="SPIRITED_AWAY_16X9_WS", bd_title="Spirited Away™ - Blu-ray")
    assert search_terms(hints) == ["Spirited Away"]  # TMDB search ignores case
    assert search_terms(DiscHints(volume_label="DVD_VIDEO")) == []


def _c(id_, title, runtime, year=2016, original_title=None) -> Candidate:
    return Candidate(id_, title, original_title or title, year, "en", runtime)


MAIN = 116 * 60 + 40  # a 1:56:40 Main Feature


def test_one_title_match_within_five_minutes_is_accepted():
    arrival = _c(329865, "Arrival", 116)
    assert decide([arrival], MAIN) == (arrival, None)
    assert decide([_c(1, "Arrival", 121)], MAIN)[0] is not None  # 4 min 20 s off
    assert decide([_c(1, "Arrival", 122)], MAIN) == (None, ReviewReason.RUNTIME_MISMATCH)


def test_two_films_that_both_fit_go_to_review():
    films = [_c(1, "Arrival", 116), _c(2, "Arrival", 113, year=1996)]
    assert decide(films, MAIN) == (None, ReviewReason.MULTIPLE_MATCHES)


def test_a_namesake_with_a_different_runtime_doesnt_stop_the_match():
    arrival = _c(329865, "Arrival", 116)
    assert decide([arrival, _c(2, "Arrival", 90, year=1996)], MAIN) == (arrival, None)


def test_nothing_found_or_no_runtime_known_goes_to_review():
    assert decide([], MAIN) == (None, ReviewReason.NO_MATCH)
    assert decide([_c(1, "Arrival", 0)], MAIN) == (None, ReviewReason.RUNTIME_MISMATCH)


def test_the_folder_follows_plex_naming_with_the_tmdb_id():
    c = Candidate(329865, "Arrival", "Arrival", 2016, "en", 116)
    assert movie_folder(c) == Path("Movies") / "Arrival (2016) {tmdb-329865}"
    c = Candidate(7, "Face/Off: Redux", "Face/Off", None, "en", 138)
    assert movie_folder(c) == Path("Movies") / "Face_Off_ Redux {tmdb-7}"


def test_bd_metadata_title_is_read_from_the_disc(tmp_path):
    assert bd_meta_title(tmp_path) == ""
    dl = tmp_path / "BDMV" / "META" / "DL"
    dl.mkdir(parents=True)
    (dl / "bdmt_jpn.xml").write_text("<di:name>メッセージ</di:name>", encoding="utf-8")
    assert bd_meta_title(tmp_path) == "メッセージ"
    (dl / "bdmt_eng.xml").write_text(
        '<?xml version="1.0"?><disclib><di:discinfo><di:title>'
        "<di:name>Arrival &amp; Friends</di:name></di:title></di:discinfo></disclib>",
        encoding="utf-8")
    assert bd_meta_title(tmp_path) == "Arrival & Friends"
