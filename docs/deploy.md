# Running and deploying on the Windows box

The app runs as the logged-on user (not a Windows service), because the MakeMKV
licence is per-user. Task Scheduler starts it at logon with `pythonw.exe`, so
there is no console window; it logs to `logs\ama.log` (see `[paths]` in the config).

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
