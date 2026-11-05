-- Video multi-disc sets (#14): a Disc attached in Review to a set already filed, and
-- which Disc of the set it is. A TV set is a series' season; a film set is the film
-- (its bonus Discs). Discs filed before #14, or on their own, have no row: they still
-- belong to the set their Episodes/film were filed as (see sets.py).
CREATE TABLE disc_sets (
    disc_id     INTEGER PRIMARY KEY REFERENCES discs(id) ON DELETE CASCADE,
    library     TEXT NOT NULL CHECK (library IN ('tv', 'movie')),
    tmdb_id     INTEGER NOT NULL,             -- the series or the film
    season      INTEGER,                      -- TV only
    disc_number INTEGER NOT NULL CHECK (disc_number >= 1),
    CHECK ((library = 'tv') = (season IS NOT NULL))
);
