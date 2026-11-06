"""CD Identification and archiving to the Archive.

`CdArchiver.run()` takes each `ripped` CD (oldest first), looks its Disc ID up
in MusicBrainz and either archives it or leaves it for Review. It archives only when
every track was verified by AccurateRip (ADR-0004) and exactly one release
(one disc of one release) carries the Disc ID. Anything else goes to Review
with its reason. The MusicBrainz answer is kept in scratch
(`musicbrainz.json`) for Review to choose from.

Archiving: tag the scratch FLACs (incl. MusicBrainz IDs), fetch the cover, and
place FLACs + cue + log + cover into `<album artist>/<album>/` in its Library
(temp name -> rename, verified; see `archive.py`). Discs of a multi-disc
release share the album folder: track files are `<disc><track:02> - <title>.flac`
and the cue/log are named per disc. Then the Job is marked archived, its scratch
deleted, and Plex asked to scan the folder.

Network trouble or an unreachable Library folder leaves the Job `ripped`; it is retried every
`retry_seconds`. Every step is idempotent, so a retry or restart just redoes it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Callable
from pathlib import Path

import httpx

from ama import archiving, cdreview, cyanrip, musicbrainz, naming
from ama.archive import Archive, safe_name
from ama.naming import Pattern, Subject
from ama.cdguess import CdPick
from ama.config import Library, LibraryKind, library_for
from ama.cdrip import CdTracks, Track
from ama.covers import Covers
from ama.cyanrip import ArStatus
from ama.flactags import write_tags
from ama.jobs import JobRecord, JobStatus, JobStore, ReviewReason
from ama.drive import DiscType
from ama.events import EventBus, Topic
from ama.media import Album, MediaStore
from ama.musicbrainz import Match, MusicBrainz
from ama.plex import Plex
from ama.problems import Problems
from ama.retry import Backoff, RetryLater

log = logging.getLogger(__name__)

MUSIC = Path("Music")
MB_FILE = cdreview.MB_FILE


# ---- deciding ----------------------------------------------------------------

def picked_match(tracks: list[Track], candidates: list[Match], pick: CdPick) -> Match | None:
    """The release the user picked, if it fits the Rip as an automatic match must (one of the
    Disc ID's releases, so its track lengths are the Disc's, with as many tracks as ripped)."""
    return next((m for m in cdreview.fitting(tracks, candidates)
                 if (m.release.id, m.disc_number) == (pick.release_id, pick.disc_number)), None)


def review_reason(tracks: list[Track], candidates: list[Match],
                  rip_accepted: bool = False, pick: CdPick | None = None) -> ReviewReason | None:
    """Why this Rip and these matches can't be archived automatically (None = archive it);
    an accepted Rip skips AccurateRip. A pick that fits is archived even when other releases
    fit too."""
    audio = cdreview.audio_tracks(tracks)  # AccurateRip doesn't cover a hidden track
    verdicts = {t.ar.status if t.ar else ArStatus.UNAVAILABLE for t in audio}
    if not rip_accepted:
        if ArStatus.MISMATCH in verdicts:
            return ReviewReason.NOT_ACCURATE
        if ArStatus.NOT_IN_DB in verdicts:
            return ReviewReason.NOT_IN_ACCURATERIP
        if ArStatus.UNAVAILABLE in verdicts:
            return ReviewReason.ACCURATERIP_UNAVAILABLE
    if pick is not None:
        return None if picked_match(tracks, candidates, pick) else ReviewReason.PICK_NOT_FITTING
    fitting = cdreview.fitting(tracks, candidates)
    if not fitting:
        return ReviewReason.NO_RELEASE
    if len(fitting) > 1:
        return ReviewReason.MULTIPLE_RELEASES
    return None


# ---- naming and tags (Plex conventions) --------------------------------------

def _music_subject(match: Match) -> Subject:
    return (Subject.MUSIC_MULTI_DISC if match.release.disc_total > 1
            else Subject.MUSIC_SINGLE_DISC)


def _music_values(match: Match, number: int = 0, title: str = "") -> dict[str, naming.Value]:
    r = match.release
    year = r.date[:4] if r.date and r.date[:4].isdigit() else None
    artist = next((t.artist for t in match.tracks if t.number == number), "")
    return {"artist": r.artist, "album": r.title, "year": year, "track": number,
            "track_title": title, "track_artist": artist, "disc": match.disc_number,
            "disc_total": r.disc_total, "disc_title": match.disc_title}


def _pattern(match: Match, library: Library | None) -> Pattern:
    """The pattern `library` files this disc by: its single- or multi-disc one, by the
    release's disc count (the defaults without a Library)."""
    subject = _music_subject(match)
    return naming.pattern_of(library, subject) if library else naming.default(subject)


def album_folder(match: Match, library: Library | None = None) -> Path:
    """The folder for this disc's tracks, cue, log and cover: by default `Music/Artist/Album`,
    one folder for all of a release's discs."""
    return MUSIC / _pattern(match, library).folders(_music_values(match))


def track_file(match: Match, number: int, title: str, library: Library | None = None) -> str:
    """By default `NN - Track.flac`, or `DNN - Track.flac` in a multi-disc release."""
    return _pattern(match, library).render(_music_values(match, number, title), ".flac").name


def disc_file_stem(match: Match) -> str:
    """Name for this disc's cue and log: the album, plus "(Disc N)" in a multi-disc set."""
    stem = safe_name(match.release.title)
    return f"{stem} (Disc {match.disc_number})" if match.release.disc_total > 1 else stem


HIDDEN_TRACK = "Hidden Track"


def track_tags(match: Match, number: int, mb_disc_id: str) -> dict[str, list[str]]:
    """Vorbis comments for track `number` (0 = hidden track), MusicBrainz Picard names."""
    r = match.release
    tags: dict[str, list[str]] = {
        "ALBUM": [r.title], "ALBUMARTIST": [r.artist],
        "TRACKNUMBER": [str(number)], "TRACKTOTAL": [str(len(match.tracks))],
        "DISCNUMBER": [str(match.disc_number)], "DISCTOTAL": [str(r.disc_total)],
        "MUSICBRAINZ_ALBUMID": [r.id], "MUSICBRAINZ_ALBUMARTISTID": list(r.artist_ids),
        "MUSICBRAINZ_DISCID": [mb_disc_id], "MEDIA": ["CD"],
    }
    track = next((t for t in match.tracks if t.number == number), None)
    if track is None:
        tags |= {"TITLE": [HIDDEN_TRACK], "ARTIST": [r.artist]}
    else:
        tags |= {"TITLE": [track.title], "ARTIST": [track.artist],
                 "MUSICBRAINZ_ARTISTID": list(track.artist_ids),
                 "MUSICBRAINZ_TRACKID": [track.recording_id],
                 "MUSICBRAINZ_RELEASETRACKID": [track.track_id]}
    optional = {"DATE": r.date, "RELEASECOUNTRY": r.country, "BARCODE": r.barcode,
                "RELEASESTATUS": r.status and r.status.lower(),
                "MUSICBRAINZ_RELEASEGROUPID": r.release_group_id,
                "DISCSUBTITLE": match.disc_title}
    tags |= {k: [v] for k, v in optional.items() if v}
    if r.labels:
        # MusicBrainz lists label + catalogue number per disc: keep each value once.
        tags["LABEL"] = list(dict.fromkeys(name for name, _ in r.labels if name))
        tags["CATALOGNUMBER"] = list(dict.fromkeys(cat for _, cat in r.labels if cat))
    if r.is_compilation:
        tags["COMPILATION"] = ["1"]
    # Details entered by hand in Review have no MusicBrainz IDs: leave those tags out.
    tags = {k: [x for x in v if x] for k, v in tags.items()}
    return {k: v for k, v in tags.items() if v}


_CUE_FILE = re.compile(r'^(\s*FILE\s+)"([^"]+)"(.*)$')


def rename_cue_files(cue: str, names: dict[str, str]) -> str:
    """Point the cue's FILE lines at the archived names ({scratch name: archived name})."""
    def fix(line: str) -> str:
        m = _CUE_FILE.match(line)
        if m and m.group(2) in names:
            return f'{m.group(1)}"{names[m.group(2)]}"{m.group(3)}'
        return line
    return "\n".join(fix(ln) for ln in cue.splitlines()) + "\n"


# ---- the worker ---------------------------------------------------------------

class CdArchiver:
    def __init__(self, jobs: JobStore, tracks: CdTracks, mb: MusicBrainz,
                 archive: Archive, plex: Plex, bus: EventBus, interval: float,
                 covers: Covers, media: MediaStore, *,
                 picked: Callable[[int], CdPick | None], retry_seconds: float = 60.0,
                 problems: Problems | None = None,
                 library: Callable[[JobRecord, LibraryKind], str | None] = lambda rec, kind: None
                 ) -> None:
        self._picked = picked  # the release the user picked while it ripped (cdguess.py)
        # The Library a Job archives to; asking locks its pick (job_settings). None = default.
        self._library = library
        self._covers = covers
        self._media = media
        self._jobs = jobs
        self._tracks = tracks
        self._mb = mb
        self._archive = archive
        self._plex = plex
        self._bus = bus
        self._interval = interval
        self.backoff = Backoff(retry_seconds, problems=problems)

    async def run(self) -> None:
        await asyncio.to_thread(self._jobs.clean_archived_scratch)
        while True:
            await self.check_once()
            await asyncio.sleep(self._interval)

    async def check_once(self) -> None:
        waiting = self._jobs.list(JobStatus.RIPPED, include_dismissed=True, types={DiscType.CD})
        for rec in reversed(waiting):  # oldest first
            if not self.backoff.due(rec.id):
                continue
            try:
                await asyncio.to_thread(self.identify, rec)
            except RetryLater as e:
                if self.backoff.later(rec.id, str(e), e.problem, e.detail):
                    self._jobs.log(rec.id, f"{e}; trying again in a while", error=True)
            except Exception:
                log.exception("CD Identification/archiving of Job %s crashed", rec.id)
                self.backoff.later(rec.id, "Identification went wrong (see the app's log file)")
            else:
                self.backoff.done(rec.id)
            self._publish()

    def _publish(self) -> None:
        for topic in (Topic.RIP, Topic.ARCHIVED, Topic.REVIEW):
            self._bus.publish(topic)

    # -- one Disc (runs in a worker thread) --
    def identify(self, rec: JobRecord) -> None:
        """Identify and file one `ripped` CD, applying the Review decision if there is one."""
        self._jobs.begin_step(rec.id, "identify", "Identification", fresh=False)
        tracks = self._tracks.load(rec.id)
        report = cyanrip.parse_report(
            (rec.scratch_dir / "rip.log").read_text(encoding="utf-8", errors="replace"))
        mb_disc_id = report.mb_disc_id or ""
        decision = cdreview.load_decision(rec.scratch_dir)
        if isinstance(decision, cdreview.ManualDetails):
            self.file(rec, cdreview.manual_match(decision), mb_disc_id)
            return
        # After Review, choose from what Review showed; otherwise ask MusicBrainz.
        response = cdreview.saved_response(rec.scratch_dir) if decision else None
        if response is None:
            try:
                response = self._mb.lookup(mb_disc_id) if mb_disc_id else None
            except httpx.HTTPError as e:
                raise RetryLater(f"Couldn't reach MusicBrainz ({e})") from e
            if response is not None:
                (rec.scratch_dir / MB_FILE).write_text(json.dumps(response, ensure_ascii=False),
                                                       encoding="utf-8")
        candidates = musicbrainz.matches(response, mb_disc_id) if response else []
        if isinstance(decision, cdreview.PickRelease):
            picked = [m for m in cdreview.fitting(tracks, candidates)
                      if (m.release.id, m.disc_number)
                      == (decision.release_id, decision.disc_number)]
            if picked:
                self.file(rec, picked[0], mb_disc_id)
                return
            self._jobs.log(rec.id, "The edition picked in Review isn't in the MusicBrainz "
                                    "answer any more", error=True)
        # The release picked while it ripped, unless Review has picked one since.
        pick = None if isinstance(decision, cdreview.PickRelease) else self._picked(rec.id)
        reason = review_reason(tracks, candidates, rip_accepted=decision is not None, pick=pick)
        if reason is not None:
            self._jobs.mark_review(rec.id, reason)
            self._jobs.log(rec.id, f"Needs Review: {reason.value.replace('_', ' ')}")
            return
        match = (picked_match(tracks, candidates, pick) if pick is not None
                 else cdreview.fitting(tracks, candidates)[0])
        assert match is not None  # review_reason checked it
        mine = "your pick, " if pick is not None else ""
        self._jobs.log(rec.id, f"Identified as {match.release.title} by {match.release.artist}, "
                                f"disc {match.disc_number} of {match.release.disc_total} "
                                f"({mine}MusicBrainz release {match.release.id})")
        self.file(rec, match, mb_disc_id)

    def file(self, rec: JobRecord, match: Match, mb_disc_id: str) -> None:
        """Tag, file and verify this Disc as `match`, then delete its scratch and tell Plex."""
        self._jobs.begin_step(rec.id, "archive", "Archive")
        scratch = rec.scratch_dir
        files: dict[str, Path] = {}
        renamed: dict[str, str] = {}
        library = self._library(rec, LibraryKind.MUSIC)
        patterned = library_for(self._archive.libraries, LibraryKind.MUSIC, library)
        for t in self._tracks.load(rec.id):
            src = scratch / f"{t.number:02d}.flac"
            title = next((x.title for x in match.tracks if x.number == t.number), HIDDEN_TRACK)
            name = track_file(match, t.number, title, patterned)
            write_tags(src, track_tags(match, t.number, mb_disc_id))
            files[name] = src
            renamed[src.name] = name
        stem = disc_file_stem(match)
        cue = scratch / "rip.cue"
        if cue.exists():
            archived_cue = scratch / "archived.cue"
            archived_cue.write_text(rename_cue_files(cue.read_text(encoding="utf-8"), renamed),
                                 encoding="utf-8")
            files[f"{stem}.cue"] = archived_cue
        files[f"{stem}.log"] = scratch / "rip.log"
        art = None
        if not match.release.id:
            self._jobs.log(rec.id, "Details entered by hand: no cover art")
        else:
            try:
                art = self._covers.release(match.release)  # cached for its History page
            except httpx.HTTPError as e:
                raise RetryLater(f"Couldn't fetch the cover art ({e})") from e
            if art is None:
                self._jobs.log(rec.id, "No cover art on the Cover Art Archive")
        if art is not None:
            cached = self._covers.path(art)
            assert cached is not None
            files[f"cover{cached.suffix}"] = cached
        rel = album_folder(match, patterned)  # the tracks' folder: cue, log and cover too
        with archiving.to_library(self._archive, rel, library):
            folder = self._archive.place(rel, files, library)
        title = f"{match.release.title} — {match.release.artist}"
        self._media.save(rec.id, Album.of(match, mb_disc_id, art))
        self._jobs.mark_archived(rec.id, title, folder)
        self._jobs.log(rec.id, f"Archived {len(files)} files to {folder}; scratch deleted")
        archiving.scan(self._plex, self._jobs, rec.id, folder)
