# Running and deploying on the Windows box

The app runs as the logged-on user (not a Windows service), because the MakeMKV
licence is per-user. Task Scheduler starts it at logon with `pythonw.exe`, so
there is no console window; it logs to `logs\ama.log` (see `[paths]` in the config).

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
`%LOCALAPPDATA%\ama\tools` (or `[tools] dir`), checks their hashes and unpacks
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
   git clone https://git.mintopia.net/mintopia/automatic-media-archive.git C:\ama
   cd C:\ama
   uv sync --frozen --no-dev
   copy ama.example.toml ama.toml   # then edit ama.toml: NAS, secrets, scratch...
   ```

3. Try it in a console first: `uv run ama` (reads `.\ama.toml`; `--config PATH`
   or `$env:AMA_CONFIG` to use another file). Open `http://<box>:8080/`. Ctrl+C to stop.
4. Let the LAN reach the port (elevated PowerShell, once):

   ```powershell
   New-NetFirewallRule -DisplayName "Automatic Media Archive" -Direction Inbound -Protocol TCP -LocalPort 8080 -Action Allow -Profile Private
   ```

5. Register the logon task (elevated PowerShell, logged in as the user who
   owns the MakeMKV licence):

   ```powershell
   $action    = New-ScheduledTaskAction -Execute "C:\ama\.venv\Scripts\pythonw.exe" -Argument "-m ama --config C:\ama\ama.toml" -WorkingDirectory "C:\ama"
   $trigger   = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
   $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
   $settings  = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
   Register-ScheduledTask -TaskName "Automatic Media Archive" -Action $action -Trigger $trigger -Principal $principal -Settings $settings
   Start-ScheduledTask -TaskName "Automatic Media Archive"
   ```

   `ExecutionTimeLimit 0` stops Windows killing it after the default 3 days;
   the restart settings bring it back if it crashes.

## Deploying an update

```powershell
cd C:\ama
git pull
uv sync --frozen --no-dev
Stop-ScheduledTask  -TaskName "Automatic Media Archive"
Start-ScheduledTask -TaskName "Automatic Media Archive"
```

Database migrations run automatically at startup. If the new version adds
settings, compare `ama.toml` with `ama.example.toml`; the app refuses to start
on unknown settings and names them.

## When it won't start

- Config problems: run `uv run ama` in a console to see the error, or read
  `ama-startup-error.log` next to the config (written when there is no console).
- Everything else: `logs\ama.log`.
- Is it running? `Get-ScheduledTask -TaskName "Automatic Media Archive" | Get-ScheduledTaskInfo`
