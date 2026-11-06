"""Golden names: the default Naming Patterns file exactly where AMA always has."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest

from ama.cdarchive import album_folder, track_file
from ama.musicbrainz import Match, Release, TrackInfo
from ama.tmdb import Candidate, movie_folder, movie_path
from ama.tv import Episode, Series, episode_path, season_path, series_folder

OCEANS = Candidate(161, "Ocean's Eleven", "Ocean's Eleven", 2001, "en", 116)


@pytest.mark.parametrize("film, version, path", [
    (OCEANS, "4K", "Ocean's Eleven (2001) {tmdb-161}/Ocean's Eleven (2001) {tmdb-161} - 4K.mkv"),
    (OCEANS, "1080p",
     "Ocean's Eleven (2001) {tmdb-161}/Ocean's Eleven (2001) {tmdb-161} - 1080p.mkv"),
    (OCEANS, None, "Ocean's Eleven (2001) {tmdb-161}/Ocean's Eleven (2001) {tmdb-161}.mkv"),
    (Candidate(7, "Face/Off: Redux", "", None, "en", 138), "1080p",
     "Face_Off_ Redux {tmdb-7}/Face_Off_ Redux {tmdb-7} - 1080p.mkv"),
    (Candidate(50646, "Crazy, Stupid, Love.", "", 2011, "en", 118), None,
     "Crazy, Stupid, Love. (2011) {tmdb-50646}/Crazy, Stupid, Love. (2011) {tmdb-50646}.mkv"),
])
def test_films_each_version(film, version, path):
    assert movie_path(film, version) == Path("Movies") / path
    assert movie_folder(film) == movie_path(film, version).parent


FIREFLY = Series(1437, "Firefly", 2002)


@pytest.mark.parametrize("series, episode, path", [
    (FIREFLY, Episode(1, 2, "The Train Job"),
     "Firefly (2002) {tmdb-1437}/Season 01/Firefly - s01e02 - The Train Job.mkv"),
    (FIREFLY, Episode(1, 3, ""), "Firefly (2002) {tmdb-1437}/Season 01/Firefly - s01e03.mkv"),
    (FIREFLY, Episode(0, 1, "Here's How It Was: The Making of Firefly"),
     "Firefly (2002) {tmdb-1437}/Season 00/"
     "Firefly - s00e01 - Here's How It Was_ The Making of Firefly.mkv"),
    (Series(1, "Show", None), Episode(12, 103, ""), "Show {tmdb-1}/Season 12/Show - s12e103.mkv"),
    (Series(71790, "S.W.A.T.", 2017), Episode(1, 1, "Pilot."),
     "S.W.A.T. (2017) {tmdb-71790}/Season 01/S.W.A.T - s01e01 - Pilot.mkv"),
])
def test_tv_with_and_without_an_episode_name_and_specials(series, episode, path):
    assert episode_path(series, episode) == PurePosixPath("TV", path)
    assert season_path(series, episode.season) == episode_path(series, episode).parent
    assert series_folder(series) == episode_path(series, episode).parent.parent


def _queen(disc_total: int, disc: int = 1) -> Match:
    release = Release("r", "Greatest Hits", "Queen", ("q",), disc_total)
    return Match(release, disc, "", (TrackInfo(1, "Bohemian Rhapsody", "Queen", (), "", ""),))


def test_single_disc_music():
    assert album_folder(_queen(1)) == Path("Music/Queen/Greatest Hits")
    assert track_file(_queen(1), 1, "Bohemian Rhapsody") == "01 - Bohemian Rhapsody.flac"
    assert track_file(_queen(1), 0, "Hidden Track") == "00 - Hidden Track.flac"
    assert track_file(_queen(1), 17, "We Are the Champions?") == "17 - We Are the Champions_.flac"


def test_multi_disc_music():
    assert album_folder(_queen(3, 2)) == Path("Music/Queen/Greatest Hits")
    assert track_file(_queen(3, 1), 1, "Bohemian Rhapsody") == "101 - Bohemian Rhapsody.flac"
    assert track_file(_queen(3, 2), 12, "Innuendo") == "212 - Innuendo.flac"
