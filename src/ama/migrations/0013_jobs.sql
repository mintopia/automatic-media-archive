-- v2 (#21): a `discs` row was really a Job (one Disc's pass through the pipeline), so the
-- schema is recreated around `jobs`. No data is migrated: v1's rows are dropped (`kv`,
-- the session secret, is kept). The whole v2 schema is here, so later migrations build
-- on this file rather than 0002-0012.
DROP TABLE IF EXISTS media_info;
DROP TABLE IF EXISTS disc_sets;
DROP TABLE IF EXISTS extras;
DROP TABLE IF EXISTS tv_titles;
DROP TABLE IF EXISTS disc_fingerprints;
DROP TABLE IF EXISTS movies;
DROP TABLE IF EXISTS cd_tracks;
DROP TABLE IF EXISTS titles;
DROP TABLE IF EXISTS disc_log;
DROP TABLE IF EXISTS discs;

-- One row per Job: a Disc inserted and Ripped (or tried). Shared by CD and video Jobs.
CREATE TABLE jobs (
    id                 INTEGER PRIMARY KEY,
    disc_type          TEXT NOT NULL,                 -- DiscType value: CD, DVD, BD, UHD
    label              TEXT NOT NULL DEFAULT '',      -- the Disc's volume label
    status             TEXT NOT NULL
                       CHECK (status IN ('ripping', 'ripped', 'review', 'filed', 'failed')),
    failure_kind       TEXT,                          -- FailureKind value when failed
    failure_headline   TEXT,                          -- one sentence for the UI
    failure_advice     TEXT,                          -- what the user can do about it
    scratch_dir        TEXT NOT NULL,
    -- Titles left out of a video Rip (always 0 for a CD)
    skipped_short      INTEGER NOT NULL DEFAULT 0,
    skipped_duplicates INTEGER NOT NULL DEFAULT 0,
    started_at         TEXT NOT NULL,                 -- ISO 8601, local time
    finished_at        TEXT,                          -- the Rip finished
    dismissed          INTEGER NOT NULL DEFAULT 0,
    review_reason      TEXT,                          -- ReviewReason value when status = review
    title              TEXT NOT NULL DEFAULT '',      -- what it was filed as, e.g. "Kid A — Radiohead"
    archive_dir        TEXT,                          -- the Archive folder it was filed into
    filed_at           TEXT
);

-- The Job's log shown in the UI: the tools' own output plus AMA's steps.
CREATE TABLE job_log (
    id     INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    at     TEXT NOT NULL,                           -- ISO 8601, local time
    error  INTEGER NOT NULL DEFAULT 0,
    text   TEXT NOT NULL
);
CREATE INDEX job_log_job ON job_log(job_id, id);

-- Titles of a video Disc chosen for the Job's Rip.
CREATE TABLE titles (
    job_id     INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    number     INTEGER NOT NULL,          -- 1-based, as shown to people
    makemkv_id INTEGER NOT NULL,          -- makemkvcon's Title id for this scan
    duration_s INTEGER NOT NULL,
    size_bytes INTEGER NOT NULL,
    audio      INTEGER NOT NULL,
    subtitles  INTEGER NOT NULL,
    segments   TEXT NOT NULL,
    file       TEXT NOT NULL,             -- file name inside the Job's scratch_dir
    status     TEXT NOT NULL CHECK (status IN ('waiting', 'ripping', 'ripped', 'failed')),
    source     TEXT NOT NULL DEFAULT '',  -- the Disc playlist it plays (TINFO 16), e.g. "00800.mpls"
    name       TEXT NOT NULL DEFAULT '',  -- MakeMKV's name for the Title (TINFO 2)
    PRIMARY KEY (job_id, number)
);

-- Per-track results of a CD Rip (track 0 = hidden track before track 1).
CREATE TABLE cd_tracks (
    job_id        INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    number        INTEGER NOT NULL,
    seconds       REAL NOT NULL,
    preemphasis   INTEGER NOT NULL DEFAULT 0,
    ripped        INTEGER NOT NULL DEFAULT 0,
    ar_status     TEXT,         -- accurate | mismatch | not_in_db | unavailable (NULL until ripped)
    ar_confidence INTEGER,      -- set when ar_status = 'accurate'
    PRIMARY KEY (job_id, number)
);

-- A video Job Identified as a film: what it is, which Title is the Main Feature, and
-- where its Title Encode is in the queue (FIFO by queued_at, then job_id). The Job
-- stays `ripped` until it is filed.
CREATE TABLE movies (
    job_id            INTEGER PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
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

-- Repeat-Disc warning: what each Job's Disc was, so a filed one is recognised when it
-- goes back in the drive. "CD:<MusicBrainz Disc ID>" or "<BD|UHD|DVD>:<sha256 of the
-- Disc's file structure>"; the Disc Type is part of it, so a BD and a UHD differ.
CREATE TABLE disc_fingerprints (
    job_id      INTEGER PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
    fingerprint TEXT NOT NULL
);
CREATE INDEX disc_fingerprints_by_fingerprint ON disc_fingerprints (fingerprint);

-- The Titles of a TV Job that Review kept: each is an Episode of the series (season 0
-- = specials) or an Extra (season/episode NULL), where it is filed in the Archive, and
-- its Title Encode's place in the queue. Discarded Titles have no row. The Job stays
-- `ripped` until every row is filed.
CREATE TABLE tv_titles (
    job_id            INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
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
    PRIMARY KEY (job_id, title_number)
);

-- Each Extra of a movie Job: every ripped Title that isn't the Main Feature, Encoded
-- and filed to the film's folder.
CREATE TABLE extras (
    job_id        INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    title_number  INTEGER NOT NULL,            -- titles.number
    name          TEXT NOT NULL,               -- the name in Plex (file name without .mkv)
    category      TEXT NOT NULL DEFAULT 'Other',  -- the Plex extras folder, e.g. 'Featurettes'
    status        TEXT NOT NULL DEFAULT 'queued'
                  CHECK (status IN ('queued', 'encoding', 'encoded', 'failed', 'filed')),
    file          TEXT NOT NULL DEFAULT '',    -- once named for filing: 'Other/Name.mkv',
                                               -- relative to the film's folder
    reviewed      INTEGER NOT NULL DEFAULT 0,  -- the user sorted them, or left them as they are
    PRIMARY KEY (job_id, title_number)
);

-- Video multi-disc sets: a Job whose Disc Review attached to a set already filed, and
-- which Disc of the set it is. A TV set is a series' season; a film set is the film
-- (its bonus Discs). Jobs filed on their own have no row: they still belong to the set
-- their Episodes/film were filed as (see sets.py).
CREATE TABLE disc_sets (
    job_id      INTEGER PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
    library     TEXT NOT NULL CHECK (library IN ('tv', 'movie')),
    tmdb_id     INTEGER NOT NULL,             -- the series or the film
    season      INTEGER,                      -- TV only
    disc_number INTEGER NOT NULL CHECK (disc_number >= 1),
    CHECK ((library = 'tv') = (season IS NOT NULL))
);

-- What a filed Job is, for its History page (media.py): the album (MusicBrainz) or the
-- film/series (TMDB) it was filed as, as JSON. Cover art and posters are cached files
-- next to the state DB (covers.py); `info` names them.
CREATE TABLE media_info (
    job_id INTEGER PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
    info   TEXT NOT NULL
);
