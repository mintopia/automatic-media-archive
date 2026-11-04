-- A video Disc Identified as a film (#6): what it is, which Title is the Main
-- Feature, and where it is in the Encode queue (FIFO by queued_at, then disc_id).
-- The Disc stays `ripped` in `discs` until it is filed.
CREATE TABLE movies (
    disc_id           INTEGER PRIMARY KEY REFERENCES discs(id) ON DELETE CASCADE,
    tmdb_id           INTEGER NOT NULL,
    title             TEXT NOT NULL,
    original_title    TEXT NOT NULL DEFAULT '',
    year              INTEGER,
    original_language TEXT NOT NULL DEFAULT '',   -- ISO 639-1, from TMDB
    runtime_min       INTEGER NOT NULL DEFAULT 0,
    title_number      INTEGER NOT NULL,           -- the Main Feature (titles.number)
    encode_status     TEXT NOT NULL
                      CHECK (encode_status IN ('queued', 'encoding', 'encoded', 'failed')),
    video_height      INTEGER NOT NULL DEFAULT 0, -- of the Encode, e.g. 1080
    queued_at         TEXT NOT NULL
);
