"""TV's pure parts: when a video Disc looks like TV, which Title is a "Play all",
and where an Episode is filed (Plex TV naming)."""

from __future__ import annotations

from pathlib import PurePosixPath

from ama.jobs import TitleRecord, TitleStatus
from ama.tmdb import DiscHints
from ama.tv import Episode, Series, episode_path, extra_path, looks_like_tv, \
    might_be_tv, play_alls, series_terms


def _t(number: int, minutes: float, segments: str = "") -> TitleRecord:
    return TitleRecord(number, number - 1, int(minutes * 60), 1, 1, 0, segments,
                       f"t{number:02d}.mkv", TitleStatus.RIPPED)


OFFICE = Series(2996, "The Office", 2001, "en")


def test_several_episode_length_titles_look_like_tv_and_a_film_with_extras_does_not():
    episodes = [_t(1, 29, "1"), _t(2, 29.5, "2"), _t(3, 30, "3"), _t(4, 88.5, "1,2,3")]
    assert looks_like_tv(episodes)
    assert looks_like_tv([_t(1, 44), _t(2, 46), _t(3, 45)])  # hour-long episodes
    # Two of them could be a film's cuts: only a TMDB series match says TV (see might_be_tv).
    assert not looks_like_tv([_t(1, 44), _t(2, 46)]) and might_be_tv([_t(1, 44), _t(2, 46)])
    film_with_extras = [_t(1, 121), _t(2, 24), _t(3, 18), _t(4, 22), _t(5, 3)]
    assert not looks_like_tv(film_with_extras)
    assert not looks_like_tv([_t(1, 121)])
    assert not looks_like_tv([_t(1, 25)])  # one short Title: could be anything, not TV-shaped
    failed = TitleRecord(2, 1, 29 * 60, 1, 1, 0, "", "t02.mkv", TitleStatus.FAILED)
    assert not looks_like_tv([_t(1, 29), failed])


def test_a_films_cuts_or_a_film_and_a_long_documentary_are_not_tv():
    cuts = [_t(1, 120), _t(2, 130), _t(3, 12)]
    assert not looks_like_tv(cuts) and not might_be_tv(cuts)
    with_documentary = [_t(1, 118), _t(2, 97), _t(3, 6)]
    assert not looks_like_tv(with_documentary) and not might_be_tv(with_documentary)
    feature_length = [_t(1, 88), _t(2, 89), _t(3, 87)]  # well over episode length
    assert not looks_like_tv(feature_length)


def test_a_play_all_is_the_title_made_of_other_titles():
    by_segments = [_t(1, 29, "1"), _t(2, 29, "2"), _t(3, 30, "3-4"), _t(4, 88, "1,2,3-4"),
                   _t(5, 3, "9")]
    assert play_alls(by_segments) == {4}
    # No segment map (some DVDs): a Title as long as the others put together.
    by_length = [_t(1, 29), _t(2, 29.5), _t(3, 30), _t(4, 88.6), _t(5, 3)]
    assert play_alls(by_length) == {4}
    assert play_alls([_t(1, 121), _t(2, 24), _t(3, 18)]) == set()


def test_episodes_are_filed_with_plex_tv_naming_and_specials_in_season_00():
    assert episode_path(OFFICE, Episode(1, 4, "The Quiz")) == PurePosixPath(
        "TV/The Office (2001) {tmdb-2996}/Season 01/The Office - s01e04 - The Quiz.mkv")
    assert episode_path(OFFICE, Episode(0, 2, "Christmas Special: Part 2")) == PurePosixPath(
        "TV/The Office (2001) {tmdb-2996}/Season 00/The Office - s00e02 - "
        "Christmas Special_ Part 2.mkv")
    assert episode_path(Series(1, "Show", None), Episode(12, 103, "")) == PurePosixPath(
        "TV/Show {tmdb-1}/Season 12/Show - s12e103.mkv")
    assert extra_path(OFFICE, "THE_OFFICE_S1_D2 - Title 5") == PurePosixPath(
        "TV/The Office (2001) {tmdb-2996}/Other/THE_OFFICE_S1_D2 - Title 5.mkv")


def test_series_search_terms_drop_season_and_disc_numbers():
    assert series_terms(DiscHints(volume_label="THE_OFFICE_S1_D2")) == ["THE OFFICE"]
    assert series_terms(DiscHints(volume_label="BAND_OF_BROTHERS_DISC_3",
                                  disc_name="Band of Brothers: Season 1 - Disc 3")) == [
        "Band of Brothers"]  # the same name from the label isn't searched twice
    assert series_terms(DiscHints(disc_name="Sherlock Series 2")) == ["Sherlock"]
