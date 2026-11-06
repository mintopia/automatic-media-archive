---
layout: ../../layouts/Docs.astro
slug: how-a-disc-flows
description: What happens to a Disc from the drive to your Plex Library, and when AMA asks you.
---

Each Disc you put in becomes a **Job**: one pass from the drive to your Library. A Job is always in one of four Phases, and the Now page groups Jobs by Phase:

<ol class="num">
  <li><b>Ripping</b>: AMA copies the Disc to Scratch and ejects it.</li>
  <li><b>Review</b>: only when AMA can’t tell what the Disc is.</li>
  <li><b>Encoding</b>: films and TV are made into their final, smaller files.</li>
  <li><b>Archived</b>: named, moved into the Library and listed in History.</li>
</ol>

A Job that can’t go on is **Failed** and shows under **Didn’t work** on the Now page, with what went wrong.

The drive is the slow part, so AMA rips first and does the rest afterwards, from Scratch. You can feed it Disc after Disc while earlier ones are still encoding.

## Ripping

When a Disc goes in, AMA works out its Disc Type (CD, DVD, Blu-ray or UHD Blu-ray) and starts the Rip: a straight copy, with nothing thrown away yet.

- **CDs** are read with cyanrip into lossless FLAC, one file per Track. Each Track is checked against AccurateRip, which compares it with other people’s rips of the same CD.
- **DVDs and Blu-rays** are read with MakeMKV. AMA rips every Title of 30 seconds or more, and leaves out shorter ones (menus, logos, warnings) and exact duplicates. On the rip card you can untick a Title before its turn comes, to skip it.

While it rips, the rip card shows AMA’s **Best guess** of what the Disc is, from its label. If it’s wrong, choose **Change the film** and pick the right one, or **It’s TV, not a film**. For a CD, pick the edition you have. A pick that fits the Rip is accepted without Review.

When the Rip is done, AMA ejects the Disc and, if you’ve set up alerts, tells you to put the next one in.

AMA won’t start a Rip when:

- **Scratch is too full** for this Disc Type. It ejects the Disc unripped and shows what’s using the space. Finishing a Review or an Encode frees some.
- **The Disc is already in your Archive**, or ripped and on its way there. It waits until you choose whether to rip it again.
- **AMA is Paused**, from the menu. It ignores new Discs; anything already under way carries on.

## Identification

Once a Disc is ripped, AMA works out what it is.

- **CDs** are looked up on MusicBrainz by the CD’s Disc ID, which gives the album, artist, Track titles and cover.
- **Films** are looked up on TMDB by the Disc’s name. A match is accepted only if its running time is within 5 minutes of the Main Feature, the Title that is the film itself.
- **TV** always goes to Review, because only you can say which Title is which Episode.

When AMA is sure, the Job carries straight on. Otherwise it goes to Review.

## Review

Review is AMA asking rather than guessing. The Review page lists every Disc waiting for you, and each asks one question:

<table class="kv">
  <thead><tr><th scope="col">Why it’s there</th><th scope="col">What you do</th></tr></thead>
  <tbody>
    <tr><td>Two films fit the Disc’s name and length</td><td>Pick the film, and check which Title is the Main Feature from the stills AMA takes of each Title.</td></tr>
    <tr><td>No film on TMDB fits</td><td>Search TMDB for the right one.</td></tr>
    <tr><td>Several Titles run the film’s length but play its scenes out of order</td><td>Pick the Title that plays in order. Some Blu-rays hide the film among such decoys.</td></tr>
    <tr><td>It looks like TV</td><td>Choose the series and season, then which Episode each Title is. AMA suggests an order.</td></tr>
    <tr><td>MusicBrainz knows several editions of the CD, or none</td><td>Pick your edition from their track lists, or enter the album, artist, year and track titles yourself.</td></tr>
    <tr><td>A Track didn’t match AccurateRip, or couldn’t be checked</td><td>Keep the Rip as it is, or discard it, clean the CD and rip it again.</td></tr>
  </tbody>
</table>

The Disc is long gone from the drive by now: Review works from the Rip in Scratch, so you can answer it whenever suits you, from any device.

**Sets.** When a Disc looks like part of something already archived, such as Firefly Disc 2 after Disc 1, Review first asks whether it is, and which Disc of the set. A TV Disc then carries on from the Episodes the earlier Discs archived. A film’s **Extras Disc** has its Titles archived as Extras of that film.

## Encoding

Films and TV are encoded to MKV files at the quality you set for each Disc Type: HEVC by default, or AV1 on an NVIDIA card that has it. You choose the encoder in Settings: an NVIDIA or Intel graphics card, or the processor (much slower). AMA test-encodes with each one when it starts, and one that doesn’t work on your PC can’t be chosen. Only one Title Encode runs at a time, and the Now page shows each one’s progress.

- **DVDs** are deinterlaced where they need it and have their black bars cropped.
- **UHD Blu-rays** keep HDR10. Dolby Vision and HDR10+ are not kept.
- **Sound tracks and subtitles** follow your language settings: by default, tracks in your languages plus the film’s original language.
- **Extras** are encoded after the Main Feature.

CDs are not encoded: their FLAC files are the Archive, with tags written from MusicBrainz.

Encode settings live in Settings and apply to every Job whose Encode hasn’t started. The [Settings reference](../settings/#encode) lists them.

## Archived

AMA names each file with the Library’s [Naming Pattern](../libraries/), moves it into the Library, and, if Plex is connected, asks Plex to scan that folder. The Rip is then deleted from Scratch: for video, the Encode is the Archive and no full-size copy is kept.

- A **film** goes in its own folder, with its Extras in an `Other` folder inside it.
- **TV Episodes** go into the show’s season folder, and its Extras into the show’s `Other` folder.
- A **CD** goes into the album’s folder: its Tracks, plus the rip log, cue sheet and `cover.jpg`.

The Job joins **History**, which lists every archived Disc, newest first, with its cover or poster, its Tracks or Episodes, and where its details came from.

If the Library’s folder can’t be reached, for example a NAS that’s asleep, the Job waits and AMA tries again every minute.

## When something fails

A Failed Job shows under **Didn’t work** on the Now page, and its page says what went wrong and what to try. Every Job’s full record is in **Logs**: each tool AMA ran, with its output.

A Rip that fails is ejected. An Encode that fails keeps its Rip in Scratch and is tried again the next time AMA starts. Kept Rips are cleared out, oldest first, by **Scratch cleanup**, once they pass the age you set or when Scratch runs short of space. Both are in the [Settings reference](../settings/#scratch).
