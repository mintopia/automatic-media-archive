-- A video Job's TV Best guess, the series it most likely is: searched on TMDB from the
-- Disc's names once the user marks the Disc as TV while it rips, or picked by the user on
-- the rip card. TV Review starts from it. `series` is the TMDB series as JSON
-- (tmdb.Series); `poster` its cached poster (covers.py).
CREATE TABLE series_guesses (
    job_id INTEGER PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
    series TEXT NOT NULL,
    poster TEXT,
    picked INTEGER NOT NULL DEFAULT 0  -- 1: the user chose it; a later automatic guess keeps it
);
