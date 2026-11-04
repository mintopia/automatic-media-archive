# Decision: The TOML file is the single source of truth for settings

Status: accepted
Date: 2026-11-04

## Context
Settings are being made editable in the UI. They could be stored as overrides
in the SQLite `kv` table merged over the TOML file, or the UI could edit the
TOML file itself. Two sources would make it unclear which value is live and
which one a hand edit should touch.

## Decision
`ama.toml` stays the only settings source. The UI validates an edit through the
same config models used at startup, then writes the file in place with
`tomlkit` (keeping comments and key order), atomically, with one `.bak` kept.
Keys that can apply live do; the rest save and show a "restart required"
banner. The `kv` table is not used for settings.

## Consequences
- Hand-editing the file and editing in the UI are equivalent.
- Adds a `tomlkit` dependency, because `tomllib` only reads.
- Every setting must be expressible in TOML and validated by the config models.

## Supersedes
None
