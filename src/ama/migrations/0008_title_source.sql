-- The Disc playlist each video Title plays (makemkvcon TINFO 16, e.g. "00800.mpls"), so
-- Review can name decoy playlists (#9). Titles ripped before this have ''.
ALTER TABLE titles ADD COLUMN source TEXT NOT NULL DEFAULT '';
