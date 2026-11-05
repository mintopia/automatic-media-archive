# Automatic Media Archive

Semi-automated archiving of the owner's own physical optical media into a Plex-served library on a NAS.

## Media

**Disc**:
A single physical optical medium inserted into the drive: Audio CD, DVD-Video, Blu-ray or UHD Blu-ray.
_Avoid_: Media, volume

**Job**:
One Disc's single pass through the pipeline, from insertion to Filed or Failed. It carries the Phase, the Identification and the settings locked so far; inserting the same Disc again starts a new Job.
_Avoid_: Run (that's its log record), task, rip (as a noun for the whole pass)

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
Lossy transcoding of a ripped video Title into its archived form. A Job's Encode Phase covers one Title Encode per Title.
_Avoid_: Transcode, convert, compress

**Title Encode**:
The Encode of one Title of a Job (the Main Feature, an Extra or an Episode), with its own place in the Encode queue and its own status. Only one Title Encode runs at a time.
_Avoid_: Job, encode job (a Job is the whole pass of a Disc)

**Identification**:
Matching a Disc to its real-world release (album, film, series) so it can be named and filed.
_Avoid_: Lookup, matching, tagging

**Best guess**:
The film a video Job most likely is, kept on the Job from the Rip on: guessed from the volume label (re-ranked by runtime once the longest Title is known) or picked by the user on the rip card. Review starts from it; only Identification and Review decide. A picked film whose runtime fits the Main Feature is accepted by Identification like an automatic match (no Review); likewise a CD release picked on the rip card that fits the Rip, once AccurateRip has verified it.
_Avoid_: Likely film, match (a Best guess is not an Identification)

**Review**:
A human confirming or correcting an Identification whose confidence was too low to accept automatically.
_Avoid_: Approval, triage

**Phase**:
The single user-facing stage a Job is in: Ripping, Review, Encoding, Filed or Failed. Every status shown in the UI is one of these; finer internal states display as the Phase they belong to.
_Avoid_: Status, stage, step

**Run**:
One entry in Logs: a Job's record of its Steps, or an app event (startup, NAS connect or drop, tool download) with Steps of its own. A Job has exactly one Run; "Run" names the log record, never the Job itself.
_Avoid_: Build, execution

**Step**:
One tool run or action inside a Run, with its own output and result: Rip, Identification, one Title Encode per Title, and File for a Job. Steps are detail inside a Phase, never a Phase.
_Avoid_: Task, stage

**Paused**:
AMA ignores newly inserted Discs; a Rip already under way finishes and every other Phase carries on.
_Avoid_: Stopped, disabled, idle

## Output

**Archive**:
The final, named, Plex-ready files on the NAS. For CDs this is lossless; for video Discs it is the Encode, and no lossless copy is kept.
_Avoid_: Backup, master

**Library**:
A named folder of the Archive for one kind of media (films, TV, music), matching one Plex library. Each kind has a default Library; a Job may be sent to another of the same kind.
_Avoid_: Destination, section, collection

**History**:
The UI section listing every Job filed to the Archive, newest first, with what it was filed as (cover or poster, tracks or overview, sources). A Job's page is in History once it is Ripped. Only the UI wording: the Job statuses (`ripped`, `filed`) keep their names.
_Avoid_: Filed, Ripped, Archive (as the section's name)
