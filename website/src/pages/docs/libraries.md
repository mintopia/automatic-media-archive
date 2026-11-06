---
layout: ../../layouts/Docs.astro
slug: libraries
description: Where each kind of media is archived, and how its folders and files are named.
---

## Libraries

A **Library** is a folder that holds your Archive for one kind of media: films, TV or music. Point one Plex library at each.

Setup makes one of each. Change them, or add more, in **Settings › Archive › Libraries**. Each Library has:

<table class="kv">
  <thead><tr><th scope="col">Setting</th><th scope="col">What it is</th></tr></thead>
  <tbody>
    <tr><td>Name</td><td>What AMA calls it.</td></tr>
    <tr><td>Folder</td><td>The full path: a local folder, a mapped drive or a network share such as <code>\\nas\media\Movies</code>. AMA makes it if it’s missing, so check the spelling.<small>AMA doesn’t connect or mount anything. While the folder can’t be reached, Jobs for it wait, and AMA tries again every minute.</small></td></tr>
    <tr><td>Plex library</td><td>The Plex library AMA asks to scan after archiving into it. Left empty, it’s whichever Plex library’s folder holds this one.</td></tr>
    <tr><td>Naming Pattern</td><td>How the folders and files inside it are named. See below.</td></tr>
  </tbody>
</table>

Each kind has one **default** Library, where its Jobs are archived. If you have more than one of a kind, say films for the family and films for you, a Job can be sent to another one from its settings, until archiving starts. Removing a Library leaves its folder and everything archived there alone.

## Naming Patterns

A Naming Pattern is the Library’s rule for naming what is archived into it. It is written relative to the Library’s folder, with no file extension: AMA adds `.mkv` or `.flac`. The defaults are what Plex expects, so you only need to change them if you want something else.

- `{title}` is a **field**: AMA fills it in from the Identification.
- `/` starts a new folder. The last part is the file name.
- Everything else is kept as you typed it.
- `{track:02}` **pads** a number with zeros to two digits: Track 3 becomes `03`. `{episode:03}` pads to three. Padding works on any field and only with leading zeros.
- `{{` and `}}` give a literal `{` and `}`. That’s how the defaults write `{tmdb-161}`, the tag Plex reads a TMDB ID from: `{{tmdb-{tmdb_id}}}`.

Changing a Naming Pattern only affects Jobs archived afterwards. Nothing already in the Library is renamed.

### Empty fields drop out

Some fields can be empty: a DVD has no `{version}`, an Episode may have no title, a film may have no year. An empty field drops out together with the text attached to it, and the separator before it, so you don’t get stray brackets or dashes:

<table class="kv">
  <thead><tr><th scope="col">Pattern</th><th scope="col">Becomes</th></tr></thead>
  <tbody>
    <tr><td><code>{title} ({year}) - {version}</code><small>a Blu-ray</small></td><td><code>Ocean's Eleven (2001) - 1080p</code></td></tr>
    <tr><td><code>{title} ({year}) - {version}</code><small>a DVD: no version</small></td><td><code>Ocean's Eleven (2001)</code></td></tr>
    <tr><td><code>{title} [{year}] - {version}</code><small>no year, no version</small></td><td><code>Ocean's Eleven</code></td></tr>
    <tr><td><code>{show} - s{season:02}e{episode:02} - {episode_title}</code><small>an Episode with no title</small></td><td><code>Firefly - s01e03</code></td></tr>
  </tbody>
</table>

### Names Windows can use

Characters Windows can’t have in a name, such as `:` and `?`, become `_`. Over-long names are cut short, and trailing dots are removed. So *Here’s How It Was: The Making of Firefly* is archived as `Here's How It Was_ The Making of Firefly`.

### Checks

The editor previews the pattern with example names as you type, and checks it:

- **Errors** stop you saving: a field this kind of Library doesn’t have, a path that isn’t inside the Library (such as `C:\…`), an empty folder name, or a pattern that could give two files the same name. Every pattern needs enough fields to tell its files apart, and says which one is missing, for example *Needs {version}, so every file gets its own name*.
- **Warnings** let you save, but tell you Plex may struggle. They’re listed under each kind below.

Each editor also offers a few starting points under **Start from**.

## Films

<table class="kv">
  <thead><tr><th scope="col">Field</th><th scope="col">What it is</th><th scope="col">Example</th></tr></thead>
  <tbody>
    <tr><td><code>{title}</code></td><td>The film’s title on TMDB</td><td>Ocean's Eleven</td></tr>
    <tr><td><code>{year}</code></td><td>Its release year</td><td>2001</td></tr>
    <tr><td><code>{tmdb_id}</code></td><td>Its TMDB ID</td><td>161</td></tr>
    <tr><td><code>{version}</code></td><td><code>4K</code> for a UHD Blu-ray, <code>1080p</code> for a Blu-ray, empty for a DVD</td><td>1080p</td></tr>
  </tbody>
</table>

The default:

```
{title} ({year}) {{tmdb-{tmdb_id}}}/{title} ({year}) {{tmdb-{tmdb_id}}} - {version}
```

<table class="kv">
  <thead><tr><th scope="col">Disc</th><th scope="col">Archived as</th></tr></thead>
  <tbody>
    <tr><td>Blu-ray</td><td><code>Ocean's Eleven (2001) {tmdb-161}/Ocean's Eleven (2001) {tmdb-161} - 1080p.mkv</code></td></tr>
    <tr><td>UHD Blu-ray</td><td><code>Ocean's Eleven (2001) {tmdb-161}/Ocean's Eleven (2001) {tmdb-161} - 4K.mkv</code></td></tr>
    <tr><td>DVD</td><td><code>Ocean's Eleven (2001) {tmdb-161}/Ocean's Eleven (2001) {tmdb-161}.mkv</code></td></tr>
  </tbody>
</table>

The Blu-ray and the UHD of a film land side by side in one folder, and Plex shows them as two versions of the same film. The other starting points:

- **Plex, title and year**: `{title} ({year})/{title} ({year}) - {version}`, giving `Ocean's Eleven (2001)/Ocean's Eleven (2001) - 1080p.mkv`
- **By year**: `{year}/{title} ({year})/{title} ({year}) - {version}`, giving `2001/Ocean's Eleven (2001)/Ocean's Eleven (2001) - 1080p.mkv`

A film’s Extras go in an `Other` folder beside the film file.

**Needs:** `{title}` or `{tmdb_id}`, and `{version}`.<br>
**Plex warnings:** without `{year}`, or without `{tmdb_id}`, *Plex may match the wrong film*. Ocean’s Eleven is a good example: there are two.

## TV

<table class="kv">
  <thead><tr><th scope="col">Field</th><th scope="col">What it is</th><th scope="col">Example</th></tr></thead>
  <tbody>
    <tr><td><code>{show}</code></td><td>The series’ name on TMDB</td><td>Firefly</td></tr>
    <tr><td><code>{year}</code></td><td>The year it first aired</td><td>2002</td></tr>
    <tr><td><code>{tmdb_id}</code></td><td>Its TMDB ID</td><td>1437</td></tr>
    <tr><td><code>{season}</code></td><td>The season number, 0 for specials</td><td>1</td></tr>
    <tr><td><code>{episode}</code></td><td>The Episode’s number in its season</td><td>2</td></tr>
    <tr><td><code>{episode_title}</code></td><td>The Episode’s title, if it has one</td><td>The Train Job</td></tr>
  </tbody>
</table>

The default:

```
{show} ({year}) {{tmdb-{tmdb_id}}}/Season {season:02}/{show} - s{season:02}e{episode:02} - {episode_title}
```

<table class="kv">
  <thead><tr><th scope="col">Episode</th><th scope="col">Archived as</th></tr></thead>
  <tbody>
    <tr><td>Season 1, Episode 2</td><td><code>Firefly (2002) {tmdb-1437}/Season 01/Firefly - s01e02 - The Train Job.mkv</code></td></tr>
    <tr><td>A special</td><td><code>Firefly (2002) {tmdb-1437}/Season 00/Firefly - s00e01 - Here's How It Was_ The Making of Firefly.mkv</code></td></tr>
    <tr><td>No Episode title</td><td><code>Firefly (2002) {tmdb-1437}/Season 01/Firefly - s01e03.mkv</code></td></tr>
  </tbody>
</table>

The other starting points:

- **Plex, show name only**: `{show}/Season {season:02}/{show} - s{season:02}e{episode:02} - {episode_title}`
- **No season folders**: `{show} ({year}) {{tmdb-{tmdb_id}}}/{show} - s{season:02}e{episode:02} - {episode_title}`

The first folder must be the show’s own: it uses `{show}` or `{tmdb_id}` and no season or Episode field. That’s where the show’s Extras go, in an `Other` folder, and where every Disc of a season set is archived.

**Needs:** `{show}` or `{tmdb_id}`, `{season}` and `{episode}`, and a first folder for the show.<br>
**Plex warning:** Plex finds Episodes by `s01e02`, `1x02` or `01x02` in the file name. A file name without `s{season}e{episode}` or `{season}x{episode}` gets *write s{season:02}e{episode:02}*.

## Music

A music Library has two Naming Patterns: one for releases of a single disc, and one for releases of several. AMA uses the multi-disc pattern for any CD whose release has more than one disc. The fields are the same for both:

<table class="kv">
  <thead><tr><th scope="col">Field</th><th scope="col">What it is</th><th scope="col">Example</th></tr></thead>
  <tbody>
    <tr><td><code>{artist}</code></td><td>The album artist</td><td>Queen</td></tr>
    <tr><td><code>{album}</code></td><td>The album title</td><td>Greatest Hits</td></tr>
    <tr><td><code>{year}</code></td><td>The release year</td><td>1981</td></tr>
    <tr><td><code>{track}</code></td><td>The Track number on its disc</td><td>1</td></tr>
    <tr><td><code>{track_title}</code></td><td>The Track’s title</td><td>Bohemian Rhapsody</td></tr>
    <tr><td><code>{track_artist}</code></td><td>The Track’s artist</td><td>Queen</td></tr>
    <tr><td><code>{disc}</code></td><td>The disc number</td><td>1</td></tr>
    <tr><td><code>{disc_total}</code></td><td>How many discs the release has</td><td>1</td></tr>
    <tr><td><code>{disc_title}</code></td><td>The disc’s own title, if it has one</td><td>(often empty)</td></tr>
  </tbody>
</table>

The Track fields, `{track}`, `{track_title}` and `{track_artist}`, can only be in the file name: a disc’s Tracks share one folder with its rip log, cue sheet and `cover.jpg`.

### Single disc

The default, `{artist}/{album}/{track:02} - {track_title}`, files Queen’s Greatest Hits as:

```
Queen/Greatest Hits/01 - Bohemian Rhapsody.flac
Queen/Greatest Hits/02 - Another One Bites the Dust.flac
Queen/Greatest Hits/03 - Killer Queen.flac
```

The other starting point, **Artist / Album (Year)**, `{artist}/{album} ({year})/{track:02} - {track_title}`, gives `Queen/Greatest Hits (1981)/01 - Bohemian Rhapsody.flac`.

**Needs:** `{album}` and `{track}`.

### Several discs

The default, `{artist}/{album}/{disc}{track:02} - {track_title}`, puts the disc number in front of the Track number, so every disc’s Tracks sort in order in one folder: 101, 102 … 201. Track 3 of disc 2 becomes `Queen/Greatest Hits/203 - Killer Queen.flac`.

The other starting points:

- **A folder per disc**: `{artist}/{album}/Disc {disc}/{track:02} - {track_title}`, giving `Queen/Greatest Hits/Disc 2/03 - Killer Queen.flac`
- **Disc-track**: `{artist}/{album}/{disc}-{track:02} - {track_title}`, giving `Queen/Greatest Hits/2-03 - Killer Queen.flac`

**Needs:** `{album}`, `{disc}` and `{track}`.

Music patterns have no Plex warnings.
