-- v2 (#32): Logs. A Run is one entry in Logs: a Job's record of its Steps, or an app event
-- (startup, NAS, tools) with Steps of its own (GLOSSARY: Run, Step). Step output is kept per
-- Step, progress-only lines left out; command-line arguments are never stored.
CREATE TABLE runs (
    id          INTEGER PRIMARY KEY,
    kind        TEXT NOT NULL CHECK (kind IN ('job', 'app', 'nas', 'tools')),
    job_id      INTEGER UNIQUE REFERENCES jobs(id) ON DELETE CASCADE,  -- kind = 'job' only
    item        TEXT NOT NULL DEFAULT '',   -- what an app event is about: 'nas', 'cyanrip', ...
    title       TEXT NOT NULL DEFAULT '',   -- an app event's name: "AMA started", "Lost the NAS"
    detail      TEXT NOT NULL DEFAULT '',   -- its meta line: "\\nas\media · away for 3 min"
    started_at  TEXT NOT NULL,              -- ISO 8601, local time
    finished_at TEXT,
    failed      INTEGER                     -- NULL while running, then 0 (Done) or 1 (Failed)
);
CREATE INDEX runs_started ON runs(started_at);

CREATE TABLE steps (
    id          INTEGER PRIMARY KEY,
    run_id      INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    key         TEXT NOT NULL,              -- 'rip', 'identify', 'encode:3', 'file', 'nas', ...
    position    INTEGER NOT NULL,           -- order in the Run
    name        TEXT NOT NULL,              -- "Rip", "Encode", "Connect to the NAS"
    subject     TEXT NOT NULL DEFAULT '',   -- "Main Feature, Title 1"
    tool        TEXT NOT NULL DEFAULT '',   -- "ffmpeg 9.0.2"
    result      TEXT NOT NULL DEFAULT '',   -- the short result shown under the name
    state       TEXT NOT NULL CHECK (state IN ('running', 'done', 'failed')),
    exit_code   INTEGER,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    UNIQUE (run_id, key)
);

CREATE TABLE step_lines (
    id      INTEGER PRIMARY KEY,
    step_id INTEGER NOT NULL REFERENCES steps(id) ON DELETE CASCADE,
    at      TEXT NOT NULL,
    error   INTEGER NOT NULL DEFAULT 0,
    text    TEXT NOT NULL
);
CREATE INDEX step_lines_step ON step_lines(step_id, id);
