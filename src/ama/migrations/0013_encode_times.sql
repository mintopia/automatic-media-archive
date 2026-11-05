-- When each Title's Encode started and finished (Encoder), for the Job page's Steps.
-- One row per Encoded Title of a Disc: a film's Main Feature, an Extra, an Episode.
CREATE TABLE encode_times (
    disc_id      INTEGER NOT NULL REFERENCES discs(id) ON DELETE CASCADE,
    title_number INTEGER NOT NULL,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    PRIMARY KEY (disc_id, title_number)
);
