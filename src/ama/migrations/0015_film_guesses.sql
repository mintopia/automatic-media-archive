-- v2 (#22): a video Job's Best guess, the film it most likely is. Guessed from the
-- volume label while it rips (re-ranked by runtime once the Title scan has the longest
-- Title), or picked by the user on the rip card. Review starts from it. `film` is the
-- TMDB film as JSON (tmdb.Candidate); `poster` its cached poster (covers.py).
CREATE TABLE film_guesses (
    job_id INTEGER PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
    film   TEXT NOT NULL,
    poster TEXT,
    picked INTEGER NOT NULL DEFAULT 0  -- 1: the user chose it; a later automatic guess keeps it
);
