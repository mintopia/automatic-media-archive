-- Discs go on past `ripped`: to `review` (Identification needs a human) or `filed`
-- (in the Archive). SQLite can't alter a CHECK, so the table is rebuilt (foreign
-- keys are off during migrations, so child rows are kept).
CREATE TABLE discs_new (
    id                 INTEGER PRIMARY KEY,
    disc_type          TEXT NOT NULL,
    label              TEXT NOT NULL DEFAULT '',
    status             TEXT NOT NULL
                       CHECK (status IN ('ripping', 'ripped', 'review', 'filed', 'failed')),
    failure_kind       TEXT,
    failure_headline   TEXT,
    failure_advice     TEXT,
    scratch_dir        TEXT NOT NULL,
    skipped_short      INTEGER NOT NULL DEFAULT 0,
    skipped_duplicates INTEGER NOT NULL DEFAULT 0,
    started_at         TEXT NOT NULL,
    finished_at        TEXT,                          -- the Rip finished
    dismissed          INTEGER NOT NULL DEFAULT 0,
    review_reason      TEXT,                          -- ReviewReason value when status = review
    title              TEXT NOT NULL DEFAULT '',      -- what it was filed as, e.g. "Kid A — Radiohead"
    archive_dir        TEXT,                          -- the Archive folder it was filed into
    filed_at           TEXT
);
INSERT INTO discs_new (id, disc_type, label, status, failure_kind, failure_headline,
                       failure_advice, scratch_dir, skipped_short, skipped_duplicates,
                       started_at, finished_at, dismissed)
SELECT id, disc_type, label, status, failure_kind, failure_headline, failure_advice,
       scratch_dir, skipped_short, skipped_duplicates, started_at, finished_at, dismissed
FROM discs;
DROP TABLE discs;
ALTER TABLE discs_new RENAME TO discs;
