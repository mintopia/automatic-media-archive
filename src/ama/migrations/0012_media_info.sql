-- What a filed Disc is, for its History page (media.py): the album (MusicBrainz) or the
-- film/series (TMDB) it was filed as, as JSON. Cover art and posters are cached files
-- next to the state DB (covers.py); `info` names them.
CREATE TABLE media_info (
    disc_id INTEGER PRIMARY KEY REFERENCES discs(id) ON DELETE CASCADE,
    info    TEXT NOT NULL
);
