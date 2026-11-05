-- A Title the user unticked during the Rip is `skipped` (ADR 0005).
CREATE TABLE titles_new (
    job_id     INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    number     INTEGER NOT NULL,          -- 1-based, as shown to people
    makemkv_id INTEGER NOT NULL,          -- makemkvcon's Title id for this scan
    duration_s INTEGER NOT NULL,
    size_bytes INTEGER NOT NULL,
    audio      INTEGER NOT NULL,
    subtitles  INTEGER NOT NULL,
    segments   TEXT NOT NULL,
    file       TEXT NOT NULL,             -- file name inside the Job's scratch_dir
    status     TEXT NOT NULL
               CHECK (status IN ('waiting', 'ripping', 'ripped', 'failed', 'skipped')),
    source     TEXT NOT NULL DEFAULT '',  -- the Disc playlist it plays (TINFO 16), e.g. "00800.mpls"
    name       TEXT NOT NULL DEFAULT '',  -- MakeMKV's name for the Title (TINFO 2)
    PRIMARY KEY (job_id, number)
);
INSERT INTO titles_new (job_id, number, makemkv_id, duration_s, size_bytes, audio, subtitles,
                        segments, file, status, source, name)
SELECT job_id, number, makemkv_id, duration_s, size_bytes, audio, subtitles, segments, file,
       status, source, name FROM titles;
DROP TABLE titles;
ALTER TABLE titles_new RENAME TO titles;
