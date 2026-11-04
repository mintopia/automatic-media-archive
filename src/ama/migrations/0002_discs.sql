-- One row per inserted Disc that we started to Rip.
CREATE TABLE discs (
    id INTEGER PRIMARY KEY,
    disc_type TEXT NOT NULL,
    label TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ripping', 'ripped', 'failed')),
    -- set when failed: what kind (e.g. 'licence', 'title'), and the plain-language explanation
    failure TEXT,
    failure_headline TEXT,
    failure_advice TEXT,
    scratch_dir TEXT NOT NULL,
    skipped_short INTEGER NOT NULL DEFAULT 0,
    skipped_duplicates INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    dismissed INTEGER NOT NULL DEFAULT 0
);

-- The human-readable Rip log shown in the UI.
CREATE TABLE disc_log (
    id INTEGER PRIMARY KEY,
    disc_id INTEGER NOT NULL REFERENCES discs(id) ON DELETE CASCADE,
    at TEXT NOT NULL,
    error INTEGER NOT NULL DEFAULT 0,
    text TEXT NOT NULL
);
CREATE INDEX disc_log_disc ON disc_log(disc_id, id);

-- Titles of a video Disc chosen for the Rip.
CREATE TABLE titles (
    disc_id INTEGER NOT NULL REFERENCES discs(id) ON DELETE CASCADE,
    number INTEGER NOT NULL,          -- 1-based, as shown to people
    makemkv_id INTEGER NOT NULL,      -- makemkvcon's Title id for this scan
    duration_s INTEGER NOT NULL,
    size_bytes INTEGER NOT NULL,
    audio INTEGER NOT NULL,
    subtitles INTEGER NOT NULL,
    segments TEXT NOT NULL,
    file TEXT NOT NULL,               -- file name inside the Disc's scratch_dir
    status TEXT NOT NULL CHECK (status IN ('waiting', 'ripping', 'ripped', 'failed')),
    PRIMARY KEY (disc_id, number)
);
