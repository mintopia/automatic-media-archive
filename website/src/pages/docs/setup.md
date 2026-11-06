---
layout: ../../layouts/Docs.astro
slug: setup
description: The first time AMA starts it has no settings, so it opens Setup in your browser. Six short steps, then it’s ready for a Disc.
---

Setup runs on this PC only, at `http://127.0.0.1:8080/`, and AMA opens it in your browser when it starts. It asks just what AMA needs to start archiving and takes the defaults for everything else. You can go **Back** a step at any point, and nothing is saved until you finish.

Finishing writes your settings to `%LOCALAPPDATA%\AMA\ama.toml`. Setup never runs again after that: change anything later on the Settings page.

## 1. Welcome to AMA

What AMA does, and that Setup takes a minute. Choose **Get started**.

While you read, AMA starts downloading its own tools in the background: ffmpeg for Encodes and cyanrip for CD Rips. They come to about 0.5 GB, so the first start needs the internet.

## 2. Drive and MakeMKV

**Drive** lists the optical drives Windows reports, with the name MakeMKV gives each one. AMA picks the first. If you have more than one, choose the one you’ll put Discs in. No drive connected? Connect one and choose **look again**, or carry on: AMA uses the first drive it finds once it’s running.

**MakeMKV** shows whether AMA found it:

<table class="kv">
  <thead><tr><th scope="col">You see</th><th scope="col">What to do</th></tr></thead>
  <tbody>
    <tr><td>Installed and registered</td><td>Nothing. AMA uses it for DVDs and Blu-rays.</td></tr>
    <tr><td>Not found</td><td>Choose <b>Install MakeMKV</b>, install it as the Windows user AMA runs as, open it once and register it (Help, then Register). Then choose <b>Check again</b>.</td></tr>
    <tr><td>Not registered, or the key was refused</td><td>Open MakeMKV, choose Help, then Register, and enter your key. While MakeMKV is in beta, the free beta key on the MakeMKV forum works; it changes every month or two.</td></tr>
  </tbody>
</table>

MakeMKV never holds Setup up. CDs don’t need it, and AMA checks for it again once it’s running. See [Install](../install/#install-makemkv).

## 3. Where things go

AMA files each Disc into a **Library**: a folder for films, one for TV and one for music. Point your Plex libraries at the same folders.

<table class="kv">
  <thead><tr><th scope="col">Library</th><th scope="col">Starts as</th></tr></thead>
  <tbody>
    <tr><td>Films</td><td><code>Videos\Movies</code> in your user folder</td></tr>
    <tr><td>TV</td><td><code>Videos\TV</code> in your user folder</td></tr>
    <tr><td>Music</td><td><code>Music</code> in your user folder</td></tr>
  </tbody>
</table>

Each can be a local folder, a mapped drive or a network share such as `\\nas\media\Movies`. A folder that doesn’t exist yet is made when AMA first files into it, but AMA has to be able to write where it would go: Setup checks each one and says if it can’t.

**Scratch**, under Advanced, is where Discs are ripped to while they wait to be identified, reviewed and encoded. It starts as `%LOCALAPPDATA%\AMA\Scratch`. Give it a fast local disk with plenty of room: a UHD Disc can need about 100 GB.

## 4. TMDB key

AMA identifies films and TV series with The Movie Database (TMDB), using your own free API key. To get one, sign in at [themoviedb.org](https://www.themoviedb.org/), open your account settings, choose API and copy the v3 **API Key**.

- **Use my TMDB key**: paste it in. AMA checks it with TMDB before going on, and says if TMDB refused it or couldn’t be reached.
- **Skip — CDs only for now**: CDs are identified with MusicBrainz and don’t need a key. Films and TV wait unidentified until you add one in Settings, and the Now page reminds you.

## 5. Reach AMA from other devices?

You can follow a Rip or answer a Review from your phone, a tablet or another computer at home.

- **Yes** (the default): AMA can be opened from any device on your home network. Set a password, or anyone on the network can use AMA. The browser you’re using stays signed in.
- **No**: only this PC can open AMA, and it needs no password.

You can change the password later in Settings.

## 6. Ready

A summary of what you chose, where the settings file will go, and how AMA’s tool downloads are getting on. **Finish and start AMA** waits until the downloads are in. If one failed, choose **Try again**, or finish anyway: AMA keeps retrying once it’s running.

AMA then saves the settings and starts. The page opens the Now page by itself, usually within a few seconds. If you said yes to other devices, open AMA from them at this PC’s name or address on port 8080, for example `http://ama-pc:8080/`.

Put a Disc in. [How a Disc flows](../how-a-disc-flows/) explains what happens next.
