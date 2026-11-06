# Running and deploying on the Windows box

The app runs as the logged-on user (not a Windows service), because the MakeMKV
licence is per-user. Task Scheduler starts it at logon with `pythonw.exe`, so
there is no console window. Its settings file, database and logs live in
`%LOCALAPPDATA%\AMA\` (ADR 0017): `ama.toml`, `ama.sqlite3` and `logs\ama.log`.
`--config PATH` or `$env:AMA_CONFIG` names another settings file; the database and
logs then sit beside that file (see `[paths]` in it). Scratch has its own setting.

## External tools (ADR 0006)

**MakeMKV is yours to install and register. AMA never installs, updates or
registers it.** Download it from <https://www.makemkv.com/download/>, install it
while signed in as the Windows user AMA runs as, open it, and enter your key
under Help → Register. During the beta the free key is posted at
<https://forum.makemkv.com/forum/viewtopic.php?t=1053>; it changes every month
or two, and MakeMKV builds expire too ("This application version is too old"),
so expect to update or re-enter the key now and then.
At startup AMA checks that `makemkvcon64.exe` is present (in
`C:\Program Files (x86)\MakeMKV` or `C:\Program Files\MakeMKV`, or the
`[tools] makemkvcon` path), that it runs, and that it is registered
(`HKCU\Software\MakeMKV\app_Key`). Until all three pass, DVD and Blu-ray Rips are
paused and the Now page links to `/makemkv`, which says what's wrong and how to fix
it. After fixing it, press "I've fixed it, check again" there. CD Rips are unaffected.

**ffmpeg/ffprobe and cyanrip are AMA's.** On startup AMA downloads its pinned
portable builds (versions and SHA-256 in `src/ama/tools.py`) into
`%LOCALAPPDATA%\AMA\tools` (or `[tools] dir`), checks their hashes and unpacks
them. The first start needs internet and about 0.5 GB; later starts download
nothing. A corrupt tool is fetched again on the next start. Progress and
failures show on the Now page; a missing tool pauses only the work that needs it.
To use your own build instead, set its path under `[tools]` in `ama.toml`; it is
used as-is. The ffmpeg build uses NVENC, which needs a recent NVIDIA driver
(this box: 621.01 works).

### AMA's cyanrip build (ADR 0007)

cyanrip's last release (0.9.3.1) has broken AccurateRip lookups on Windows, so
AMA builds its own from a pinned upstream commit and hosts the zip in this
repo's Forgejo package registry:

| | |
|---|---|
| Upstream commit | `648b1dddd265cfd2bb69483a826eb5a5c7e7079e` (0.9.4-rc3; `-v` → `cyanrip 0.9.4-rc3 (648b1dd)`) |
| Package | `mintopia` generic package `cyanrip`, version `0.9.4-rc3-g648b1dd` |
| URL | `https://git.mintopia.net/api/packages/mintopia/generic/cyanrip/0.9.4-rc3-g648b1dd/cyanrip-0.9.4-rc3-g648b1dd-win64.zip` |
| Zip SHA-256 | `0b936259c0ecdf628e8446f42c778cf920e65de8556ccdaa0486c7b9df929d1d` |
| `cyanrip.exe` SHA-256 | `851d72c61df34a3a6af5fc44aa1711582ec33bb22e198560bb8d52c3a089a94a` |

To rebuild or move to a new commit (needs no admin rights; about 3 GB and
an hour under `%LOCALAPPDATA%\ama-build\cyanrip`):

```powershell
# 1. edit tools\cyanrip\versions.sh: CYANRIP_COMMIT, CYANRIP_VERSION, any library pins
.\tools\cyanrip\build.ps1 -Fresh -InfoDevice D:   # clean build + tests; then `cyanrip -I` on the CD in D: (never rips)
.\tools\cyanrip\build.ps1 -PublishOnly            # PUT the zip to the registry (key from ~\.forgejo); prints its sha256
# 2. update the cyanrip Pin in src\ama\tools.py and the table above; uv run pytest
```

A published version can't be replaced; a new build gets a new version. If
MSYS2 has dropped a locked toolchain package, run `build.ps1 -Relock` and
commit the new `tools\cyanrip\msys2-packages.lock`.

## First install

1. Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and git.
2. Clone and install (uv fetches Python 3.13 itself):

   ```powershell
   git clone https://github.com/mintopia/automatic-media-archive.git C:\ama
   cd C:\ama
   uv sync --frozen --no-dev
   ```

   The first `uv run ama` finds no settings file and opens Setup in the browser on
   http://127.0.0.1:8080/ (ADR 0016). It asks where the Libraries and Scratch go and
   writes `%LOCALAPPDATA%\AMA\ama.toml`; change anything else on the Settings page. To
   skip Setup, copy `ama.example.toml` there and edit it.

   Each Library is a plain folder path (ADR 0011). AMA doesn't connect to a NAS:
   if a Library is on a network share, make sure the Windows user AMA runs as can
   reach it (a mapped drive, or credentials saved in Windows). While a folder
   isn't reachable, its Jobs wait at "Encoded · filing" and filing is retried
   every minute. An `ama.toml` from v1/v2 is rewritten once at startup (its
   `[nas]` table is dropped and each Library gets its full path; a `.bak` is kept).

3. Try it in a console first: `uv run ama` (reads `%LOCALAPPDATA%\AMA\ama.toml`; `--config PATH`
   or `$env:AMA_CONFIG` to use another file). Open `http://<box>:8080/`. Ctrl+C to stop.
   `ama` (same as `ama run`) is a small supervisor that runs the server
   (`ama serve`) and starts it again when Settings' "Restart now" asks for it
   (ADR 0009). Run `ama serve` on its own and a restart from the UI just stops it.
4. Let the LAN reach the port (elevated PowerShell, once):

   ```powershell
   New-NetFirewallRule -DisplayName "Automatic Media Archive" -Direction Inbound -Protocol TCP -LocalPort 8080 -Action Allow -Profile Private
   ```

5. Start it at login, logged in as the user who owns the MakeMKV licence. Either:

   - **From the tray (no admin rights).** Start `C:\ama\.venv\Scripts\pythonw.exe -m ama run`
     once; AMA's icon appears in the notification area. Its
     menu has Open AMA (also a double-click), Pause/Resume new Discs (the same Pause
     as the UI's menu), Restart (once nothing Rips or Encodes), **Start at login**
     and Quit. Ticking Start at login adds an "Automatic Media Archive" entry under
     `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`; unticking removes it. If
     AMA crashes it stays down until the next login (or until you start it again).
   - **Or with a logon task** (below), which also brings AMA back after a crash.

   Use one or the other, not both: two copies would fight over the port.

   The logon task (elevated PowerShell):

   ```powershell
   $action    = New-ScheduledTaskAction -Execute "C:\ama\.venv\Scripts\pythonw.exe" -Argument "-m ama run" -WorkingDirectory "C:\ama"
   $trigger   = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
   $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
   $settings  = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
   Register-ScheduledTask -TaskName "Automatic Media Archive" -Action $action -Trigger $trigger -Principal $principal -Settings $settings
   Start-ScheduledTask -TaskName "Automatic Media Archive"
   ```

   `ExecutionTimeLimit 0` stops Windows killing it after the default 3 days;
   the restart settings bring it back if it crashes. A restart from the UI is
   handled by the supervisor itself, so the task keeps running through it; an
   older task registered with `-m ama --config ...` keeps working (`run` is the default).

## Webhook alerts

With `[webhook] url` set, every alert is one POST of versioned JSON:

```json
{"version": 1, "event": "job_filed", "at": "2026-11-05T12:00:00Z",
 "job": {"id": 7, "disc_type": "bd", "title": "...", "status": "filed", "url": "..."}}
```

`event` is `rip_done`, `review_needed`, `job_filed` or `job_failed`, or `test` from
Settings' "Send test", whose `job` is null. `at` is UTC. `title` is what the Job was
filed as, else its Disc label; `url` is the Job's page. Ignore keys you don't know; a
change to existing keys gets a new `version`.

## Deploying an update

```powershell
cd C:\ama
git pull
uv sync --frozen --no-dev
Stop-ScheduledTask  -TaskName "Automatic Media Archive"
Start-ScheduledTask -TaskName "Automatic Media Archive"
```

Database migrations run automatically at startup. If the new version adds
settings, compare `%LOCALAPPDATA%\AMA\ama.toml` with `ama.example.toml`; the app refuses to start
on unknown settings and names them.

## Moving an existing install to %LOCALAPPDATA%\AMA (once)

Before Phase 4, AMA kept `ama.toml`, `ama.sqlite3` and `logs\` beside the clone
(`C:\ama`). It now looks in `%LOCALAPPDATA%\AMA\` unless `--config` or
`AMA_CONFIG` says otherwise (ADR 0017). An install that still starts with
`--config C:\ama\ama.toml` keeps working; to move it:

1. Quit AMA from the tray (or `Stop-ScheduledTask -TaskName "Automatic Media Archive"`).
   Nothing should be Ripping or Encoding.
2. If `[paths] scratch` in `ama.toml` is a relative path, make it a full one
   (for example `'C:\ama\scratch'`): relative paths follow the settings file.
3. Move the files (PowerShell):

   ```powershell
   $to = "$env:LOCALAPPDATA\AMA"
   New-Item -ItemType Directory -Force $to | Out-Null
   Move-Item C:\ama\ama.toml, C:\ama\ama.toml.bak, C:\ama\ama.sqlite3* $to -ErrorAction SilentlyContinue
   Move-Item C:\ama\logs $to
   ```

   `ama.sqlite3*` also moves the database's `-wal` and `-shm` files if they are there.
4. Drop `--config C:\ama\ama.toml` from however AMA starts:
   - the logon task: register it again with `-Argument "-m ama run"` (above);
   - the tray's **Start at login**: untick it and tick it again once AMA is running
     from the new place.
5. Start AMA. Its log should now be at `%LOCALAPPDATA%\AMA\logs\ama.log`.

## When it won't start

- Config problems: run `uv run ama` in a console to see the error, or read
  `ama-startup-error.log` next to the config, normally in `%LOCALAPPDATA%\AMA\`
  (written when there is no console).
- Everything else: `%LOCALAPPDATA%\AMA\logs\ama.log`.
- Is it running? `Get-ScheduledTask -TaskName "Automatic Media Archive" | Get-ScheduledTaskInfo`
