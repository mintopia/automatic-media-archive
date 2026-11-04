-- Per-track results of a CD Rip (track 0 = hidden track before track 1).
CREATE TABLE cd_tracks (
    disc_id       INTEGER NOT NULL REFERENCES discs(id) ON DELETE CASCADE,
    number        INTEGER NOT NULL,
    seconds       REAL NOT NULL,
    preemphasis   INTEGER NOT NULL DEFAULT 0,
    ripped        INTEGER NOT NULL DEFAULT 0,
    ar_status     TEXT,         -- accurate | mismatch | not_in_db | unavailable (NULL until ripped)
    ar_confidence INTEGER,      -- set when ar_status = 'accurate'
    PRIMARY KEY (disc_id, number)
);
