-- `changed_at`: when the Job last changed status; `scratch_cleaned_at`: when its Scratch went.
ALTER TABLE jobs ADD COLUMN changed_at         TEXT;  -- ISO 8601, local time
ALTER TABLE jobs ADD COLUMN scratch_cleaned_at TEXT;  -- ISO 8601, local time
UPDATE jobs SET changed_at = COALESCE(filed_at, finished_at, started_at);

-- A Scratch cleanup is a Run of its own kind ('scratch'): `runs` is rebuilt for the CHECK.
CREATE TABLE runs_new (
    id          INTEGER PRIMARY KEY,
    kind        TEXT NOT NULL CHECK (kind IN ('job', 'app', 'nas', 'tools', 'scratch')),
    job_id      INTEGER UNIQUE REFERENCES jobs(id) ON DELETE CASCADE,  -- kind = 'job' only
    item        TEXT NOT NULL DEFAULT '',   -- what an app event is about: 'cyanrip', ...
    title       TEXT NOT NULL DEFAULT '',   -- an app event's name: "AMA started"
    detail      TEXT NOT NULL DEFAULT '',   -- its meta line, e.g. "away for 3 min"
    started_at  TEXT NOT NULL,              -- ISO 8601, local time
    finished_at TEXT,
    failed      INTEGER                     -- NULL while running, then 0 (Done) or 1 (Failed)
);
INSERT INTO runs_new SELECT id, kind, job_id, item, title, detail, started_at, finished_at, failed
FROM runs;
DROP TABLE runs;
ALTER TABLE runs_new RENAME TO runs;
CREATE INDEX runs_started ON runs(started_at);
