-- The Filed Phase is now Archived (#82): `filed` statuses become `archived`, and
-- `jobs.filed_at` becomes `archived_at`. The CHECKs change, so the three tables are
-- rebuilt (SQLite's documented procedure; foreign keys are off while migrating).

CREATE TABLE jobs_new (
    id                 INTEGER PRIMARY KEY,
    disc_type          TEXT NOT NULL,                 -- DiscType value: CD, DVD, BD, UHD
    label              TEXT NOT NULL DEFAULT '',      -- the Disc's volume label
    status             TEXT NOT NULL
                       CHECK (status IN ('ripping', 'ripped', 'review', 'archived', 'failed')),
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
    title              TEXT NOT NULL DEFAULT '',      -- what it was archived as, e.g. "Kid A"
    archive_dir        TEXT,                          -- the Archive folder it was archived into
    archived_at        TEXT,
    min_title_seconds  INTEGER NOT NULL DEFAULT 30,
    changed_at         TEXT,                          -- ISO 8601, local time
    scratch_cleaned_at TEXT                           -- ISO 8601, local time
);
INSERT INTO jobs_new (id, disc_type, label, status, failure_kind, failure_headline,
                      failure_advice, scratch_dir, skipped_short, skipped_duplicates, started_at,
                      finished_at, dismissed, review_reason, title, archive_dir, archived_at,
                      min_title_seconds, changed_at, scratch_cleaned_at)
SELECT id, disc_type, label, CASE status WHEN 'filed' THEN 'archived' ELSE status END,
       failure_kind, failure_headline, failure_advice, scratch_dir, skipped_short,
       skipped_duplicates, started_at, finished_at, dismissed, review_reason, title,
       archive_dir, filed_at, min_title_seconds, changed_at, scratch_cleaned_at
FROM jobs;
DROP TABLE jobs;
ALTER TABLE jobs_new RENAME TO jobs;

CREATE TABLE tv_titles_new (
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
                      CHECK (encode_status IN ('queued', 'encoding', 'encoded', 'archived',
                                               'failed')),
    video_height      INTEGER NOT NULL DEFAULT 0,
    queued_at         TEXT NOT NULL,
    PRIMARY KEY (job_id, title_number)
);
INSERT INTO tv_titles_new (job_id, title_number, tmdb_id, series, year, original_language,
                           season, episode, episode_name, path, encode_status, video_height,
                           queued_at)
SELECT job_id, title_number, tmdb_id, series, year, original_language, season, episode,
       episode_name, path, CASE encode_status WHEN 'filed' THEN 'archived' ELSE encode_status END,
       video_height, queued_at
FROM tv_titles;
DROP TABLE tv_titles;
ALTER TABLE tv_titles_new RENAME TO tv_titles;

CREATE TABLE extras_new (
    job_id        INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    title_number  INTEGER NOT NULL,            -- titles.number
    name          TEXT NOT NULL,               -- the name in Plex (file name without .mkv)
    category      TEXT NOT NULL DEFAULT 'Other',  -- the Plex extras folder, e.g. 'Featurettes'
    status        TEXT NOT NULL DEFAULT 'queued'
                  CHECK (status IN ('queued', 'encoding', 'encoded', 'failed', 'archived')),
    file          TEXT NOT NULL DEFAULT '',    -- once named for archiving: 'Other/Name.mkv',
                                               -- relative to the film's folder
    reviewed      INTEGER NOT NULL DEFAULT 0,  -- the user sorted them, or left them as they are
    PRIMARY KEY (job_id, title_number)
);
INSERT INTO extras_new (job_id, title_number, name, category, status, file, reviewed)
SELECT job_id, title_number, name, category,
       CASE status WHEN 'filed' THEN 'archived' ELSE status END, file, reviewed
FROM extras;
DROP TABLE extras;
ALTER TABLE extras_new RENAME TO extras;

-- The File Step is now Archive, and the lines AMA wrote (to the Job's log and, the same
-- line, to its Run's Step) say archived. Only AMA's own phrasings are matched, with
-- case-sensitive GLOBs, so a Title merely containing "filed" is left alone.
UPDATE steps SET key = 'archive', name = 'Archive' WHERE key = 'file';
CREATE TEMP TABLE renamed (old TEXT, new TEXT);
INSERT INTO renamed VALUES
    ('All kept Titles filed to ', 'All kept Titles archived to '),
    ('; the film is filed without it', '; the film is archived without it'),
    ('Couldn''t file to ', 'Couldn''t archive to '),
    ('The Encode or filing went wrong', 'The Encode or archiving went wrong');
UPDATE job_log SET text = 'Archived ' || substr(text, 7) WHERE text GLOB 'Filed *';
UPDATE step_lines SET text = 'Archived ' || substr(text, 7) WHERE text GLOB 'Filed *';
UPDATE job_log SET text = (SELECT replace(text, old, new) FROM renamed
                           WHERE text GLOB '*' || old || '*')
WHERE EXISTS (SELECT 1 FROM renamed WHERE text GLOB '*' || old || '*');
UPDATE step_lines SET text = (SELECT replace(text, old, new) FROM renamed
                              WHERE text GLOB '*' || old || '*')
WHERE EXISTS (SELECT 1 FROM renamed WHERE text GLOB '*' || old || '*');
UPDATE steps SET result = (SELECT replace(result, old, new) FROM renamed
                           WHERE result GLOB '*' || old || '*')
WHERE EXISTS (SELECT 1 FROM renamed WHERE result GLOB '*' || old || '*');
DROP TABLE renamed;
