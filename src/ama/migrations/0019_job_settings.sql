-- v2 (#30): per-Job settings. `job_overrides` holds what the user changed for one Job
-- (key = job_settings.SETTINGS key, value as text); anything not here follows ama.toml.
-- `job_locks` is one row per settings group locked at its Phase start: the effective
-- values then, as JSON {key: [value, default]}, so later edits to ama.toml don't touch them.
CREATE TABLE job_overrides (
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    key    TEXT NOT NULL,
    value  TEXT NOT NULL,
    PRIMARY KEY (job_id, key)
);

CREATE TABLE job_locks (
    job_id    INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    grp       TEXT NOT NULL CHECK (grp IN ('rip', 'identification', 'encode', 'library')),
    locked_at TEXT NOT NULL,
    settings  TEXT NOT NULL,
    PRIMARY KEY (job_id, grp)
);
