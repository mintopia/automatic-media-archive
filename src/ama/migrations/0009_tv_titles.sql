-- The Titles of a TV Disc that Review kept (#13): each is an Episode of the series
-- (season 0 = specials) or an Extra (season/episode NULL), where it is filed in the
-- Archive, and its place in the Encode queue. Discarded Titles have no row. The Disc
-- stays `ripped` until every row is filed.
CREATE TABLE tv_titles (
    disc_id           INTEGER NOT NULL REFERENCES discs(id) ON DELETE CASCADE,
    title_number      INTEGER NOT NULL,           -- titles.number
    tmdb_id           INTEGER NOT NULL,           -- the series
    series            TEXT NOT NULL,
    year              INTEGER,
    original_language TEXT NOT NULL DEFAULT '',   -- ISO 639-1, from TMDB
    season            INTEGER,                    -- NULL for an Extra
    episode           INTEGER,
    episode_name      TEXT NOT NULL DEFAULT '',
    path              TEXT NOT NULL,              -- relative to the Archive root, '/'-separated
    encode_status     TEXT NOT NULL
                      CHECK (encode_status IN ('queued', 'encoding', 'encoded', 'filed', 'failed')),
    video_height      INTEGER NOT NULL DEFAULT 0,
    queued_at         TEXT NOT NULL,
    PRIMARY KEY (disc_id, title_number)
);
