-- One row per inserted Disc that was Ripped (or tried). Shared by CD and video Rips.
CREATE TABLE discs (
    id               INTEGER PRIMARY KEY,
    disc_type        TEXT NOT NULL,                 -- DiscType value: CD, DVD, BD, UHD
    label            TEXT NOT NULL DEFAULT '',
    status           TEXT NOT NULL CHECK (status IN ('ripping', 'ripped', 'failed')),
    failure_kind     TEXT,                          -- machine-readable reason when failed
    failure_headline TEXT,                          -- one sentence for the UI
    failure_advice   TEXT,                          -- what the user can do about it
    scratch_dir      TEXT NOT NULL,
    started_at       TEXT NOT NULL,                 -- ISO 8601, local time
    finished_at      TEXT,
    dismissed        INTEGER NOT NULL DEFAULT 0
);

-- The Rip log shown in the UI: the tool's own output plus AMA's steps.
CREATE TABLE disc_log (
    id      INTEGER PRIMARY KEY,
    disc_id INTEGER NOT NULL REFERENCES discs(id) ON DELETE CASCADE,
    at      TEXT NOT NULL,                          -- ISO 8601, local time
    error   INTEGER NOT NULL DEFAULT 0,
    text    TEXT NOT NULL
);
CREATE INDEX disc_log_disc ON disc_log(disc_id, id);
