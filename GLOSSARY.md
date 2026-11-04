# Automatic Media Archive

Semi-automated archiving of the owner's own physical optical media into a Plex-served library on a NAS.

## Media

**Disc**:
A single physical optical medium inserted into the drive: Audio CD, DVD-Video, Blu-ray or UHD Blu-ray.
_Avoid_: Media, volume

**Disc Type**:
The format class of a Disc (CD, DVD, BD, UHD) that determines how it is ripped and encoded.
_Avoid_: Media type, format

**Title**:
One playable programme on a video Disc (a film, an episode, a bonus feature), as enumerated by the drive.
_Avoid_: Playlist, track, stream

**Main Feature**:
The Title that is the film itself on a movie Disc.
_Avoid_: Main title, movie

**Extra**:
A Title that is bonus material rather than the Main Feature or an Episode.
_Avoid_: Bonus, special feature

**Episode**:
A Title that is one installment of a TV series. Mapping Titles to Episodes always requires Review.
_Avoid_: Chapter

**Extras Disc**:
A video Disc of a film's Extras with no Main Feature (often the second Disc of a set), filed as Extras of a film already in the Archive.
_Avoid_: Bonus Disc, special features Disc

## Pipeline

**Rip**:
Extracting content off a Disc to local storage with no lossy processing.
_Avoid_: Backup, extract, dump

**Encode**:
Lossy transcoding of a ripped video title into its archived form.
_Avoid_: Transcode, convert, compress

**Identification**:
Matching a Disc to its real-world release (album, film, series) so it can be named and filed.
_Avoid_: Lookup, matching, tagging

**Review**:
A human confirming or correcting an Identification whose confidence was too low to accept automatically.
_Avoid_: Approval, triage

## Output

**Archive**:
The final, named, Plex-ready files on the NAS. For CDs this is lossless; for video Discs it is the Encode, and no lossless copy is kept.
_Avoid_: Library, backup, master

**History**:
The UI section listing every Disc filed to the Archive, newest first, with what it was filed as (cover or poster, tracks or overview, sources). A Disc's page is in History once it is Ripped. Only the UI wording: the Disc statuses (`ripped`, `filed`) keep their names.
_Avoid_: Filed, Ripped, Archive (as the section's name)
