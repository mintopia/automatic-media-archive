-- Repeat-Disc warning (#16): what each Ripped Disc was, so a filed one is recognised
-- when it goes back in the drive. "CD:<MusicBrainz Disc ID>" or "<BD|UHD|DVD>:<sha256
-- of the Disc's file structure>"; the Disc Type is part of it, so a BD and a UHD differ.
CREATE TABLE disc_fingerprints (
    disc_id     INTEGER PRIMARY KEY REFERENCES discs(id) ON DELETE CASCADE,
    fingerprint TEXT NOT NULL
);
CREATE INDEX disc_fingerprints_by_fingerprint ON disc_fingerprints (fingerprint);
