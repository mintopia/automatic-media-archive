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
