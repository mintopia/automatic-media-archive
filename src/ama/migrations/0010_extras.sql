-- Extras (#8): the Title name MakeMKV reports (TINFO 2), and each Extra of a movie Disc:
-- every ripped Title that isn't the Main Feature, Encoded and filed to the film's folder.
ALTER TABLE titles ADD COLUMN name TEXT NOT NULL DEFAULT '';

CREATE TABLE extras (
    disc_id       INTEGER NOT NULL REFERENCES discs(id) ON DELETE CASCADE,
    title_number  INTEGER NOT NULL,            -- titles.number
    name          TEXT NOT NULL,               -- the name in Plex (file name without .mkv)
    category      TEXT NOT NULL DEFAULT 'Other',  -- the Plex extras folder, e.g. 'Featurettes'
    status        TEXT NOT NULL DEFAULT 'queued'
                  CHECK (status IN ('queued', 'encoding', 'encoded', 'failed', 'filed')),
    file          TEXT NOT NULL DEFAULT '',    -- once named for filing: 'Other/Name.mkv',
                                               -- relative to the film's folder
    reviewed      INTEGER NOT NULL DEFAULT 0,  -- the user sorted them, or left them as they are
    PRIMARY KEY (disc_id, title_number)
);
