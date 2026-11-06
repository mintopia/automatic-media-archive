# Automatic Media Archive

Automated extraction, encoding, renaming and archiving of removable media:

 - CD
 - DVD
 - Blu Ray

A Python app (uv) on the Windows box with the optical drive. It serves a LAN
web UI showing the drive and the pipeline, with live updates.

```powershell
uv sync                     # install (dev tools included)
uv run ruff check           # lint
uv run pytest               # tests; no hardware needed
copy ama.example.toml ama.toml
uv run ama                  # run; UI on http://localhost:8080/
```

Configuration: `ama.example.toml` documents every setting.
Running at logon and deploying updates: [docs/deploy.md](docs/deploy.md).
Contributing, branches and releases: [CONTRIBUTING.md](CONTRIBUTING.md).
