---
layout: ../../layouts/Docs.astro
slug: install
description: AMA runs on the Windows PC that has the optical drive. It installs for your user only, without admin rights, and opens Setup in your browser when it’s done.
---

## What you need

<table class="kv">
  <thead><tr><th scope="col">Thing</th><th scope="col">Why</th></tr></thead>
  <tbody>
    <tr><td>Windows 10 or 11</td><td>AMA runs as a normal app on your account and starts when you sign in.</td></tr>
    <tr><td>An optical drive</td><td>A Blu-ray drive reads every Disc Type. UHD Discs need a drive that reads them.</td></tr>
    <tr><td>MakeMKV</td><td>For DVDs and Blu-rays. You install it; AMA finds it.<small>CDs don’t need it.</small></td></tr>
    <tr><td>Plex Media Server</td><td>On this PC or another one, as long as it can see your Library folders.</td></tr>
    <tr><td>Space for scratch</td><td>A Rip waits on this PC until it’s encoded. A UHD Disc can take up to 100 GB.</td></tr>
  </tbody>
</table>

AMA downloads its other tools itself the first time it starts: [ffmpeg and cyanrip](../third-party/), at versions it has been tested with.

## Download

Get the installer from the latest release on GitHub. It’s one file, `AMA-Setup-x.y.z.exe`, where `x.y.z` is the version.

<div class="dl"><a class="btn pri big" href="https://github.com/mintopia/automatic-media-archive/releases/latest"><svg class="i" aria-hidden="true"><use href="../../icons.svg#download"/></svg>Download for Windows</a><small>Latest release on GitHub</small></div>

## Run the installer

<div class="notice" role="note"><svg class="i" aria-hidden="true"><use href="../../icons.svg#alert"/></svg><div><b>Windows will warn you first</b><p>The installer isn’t code-signed yet, so SmartScreen shows “Windows protected your PC”. Choose <b>More info</b>, check the publisher line reads Unknown publisher and the file name is <code>AMA-Setup-x.y.z.exe</code>, then choose <b>Run anyway</b>.</p></div></div>

<ol class="num">
  <li>Open the file you downloaded.</li>
  <li>Leave <b>Start AMA when I sign in</b> ticked unless you want to start it yourself from the Start menu.</li>
  <li>Choose <b>Install</b>. The installer sets up a private copy of Python and AMA’s libraries in its app folder, <code>%LOCALAPPDATA%\Programs\AMA</code>, so nothing else on the PC changes. This needs the internet and can take a few minutes.</li>
  <li>Leave <b>Start AMA now</b> ticked and choose <b>Finish</b>. AMA starts and opens <a href="../setup/">Setup</a> in your browser at <code>http://127.0.0.1:8080/</code>.</li>
</ol>

If the installer says AMA’s Python and dependencies couldn’t be installed, check the PC is online and run it again. The details are in <code>install.log</code> in the app folder.

## Install MakeMKV

AMA reads DVDs and Blu-rays with MakeMKV, which you install yourself. CDs don’t need it, so you can skip this if you only archive music.

<ol class="num">
  <li>Download MakeMKV for Windows from <a href="https://www.makemkv.com/download/">makemkv.com</a> and install it, signed in as the Windows user AMA runs as.</li>
  <li>Open MakeMKV, choose <b>Help</b>, then <b>Register</b>, and enter your key. While MakeMKV is in beta you can use the free beta key posted on the MakeMKV forum; it changes every month or two, and AMA tells you when it has run out.</li>
</ol>

AMA looks for MakeMKV in <code>C:\Program Files (x86)\MakeMKV</code> and <code>C:\Program Files\MakeMKV</code>. Installed somewhere else? Set <a href="../settings/#tools.makemkvcon"><code>makemkvcon</code></a> to the full path of <code>makemkvcon64.exe</code>. Setup shows whether AMA found it, and you can install it before or after AMA.

## Where AMA keeps its files

<table class="kv">
  <thead><tr><th scope="col">What</th><th scope="col">Where</th></tr></thead>
  <tbody>
    <tr><td>Settings</td><td><code>%LOCALAPPDATA%\AMA\ama.toml</code><small>Change them on the Settings page. The file stays readable if you’d rather edit it.</small></td></tr>
    <tr><td>History and logs</td><td><code>%LOCALAPPDATA%\AMA\</code></td></tr>
    <tr><td>Scratch</td><td>A folder you choose in Setup, under Advanced.</td></tr>
    <tr><td>Your Libraries</td><td>Wherever you point them: a local disk, a mapped drive or a network share.</td></tr>
  </tbody>
</table>

## Updates

AMA checks GitHub for a newer release and shows **Update available** with a link. It never updates itself. Download the new installer and run it over the top; your settings and History stay.

## Uninstall

Use **Add or remove programs**. Uninstalling removes the app and keeps `%LOCALAPPDATA%\AMA\`, unless you tick **Also remove settings and history**. It never touches your Libraries.
