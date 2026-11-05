-- v2 (#23): the MusicBrainz release the user picked for a CD Job while it ripped. Kept
-- after the Rip so later cards show it and Review offers it pre-selected. `cover` is the
-- cached cover file name (covers.py), NULL if the release has none.
CREATE TABLE cd_picks (
    job_id      INTEGER PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
    release_id  TEXT NOT NULL,
    disc_number INTEGER NOT NULL CHECK (disc_number >= 1),
    album       TEXT NOT NULL,
    artist      TEXT NOT NULL,
    cover       TEXT
);
