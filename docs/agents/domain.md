# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase. **Single-context** repo.

> Note: this repo keeps ADRs in **`docs/decisions/`**, not `docs/adr/`. Read "ADRs" below as `docs/decisions/`.

## Before exploring, read these

- **`GLOSSARY.md`** at the repo root.
- **`docs/decisions/`**: read the ADRs that touch the area you're about to work in.

If any of these files don't exist, **proceed silently**. Don't flag their absence or suggest creating them upfront. `/domain-modeling` creates them lazily when terms or decisions actually get resolved.

## File structure

```
/
├── GLOSSARY.md
├── docs/decisions/
│   └── 0001-ticket-cli-python.md
└── ...
```

New ADRs use the format defined in the project's root `AGENTS.md`
(Decision Memory): `# Decision: [Title]`, `Status`, `Date`, `## Context`,
`## Decision`, `## Consequences`, `## Supersedes`. Treat accepted ADRs as
binding unless the user overrides them; supersede rather than silently ignore.

## Use the glossary's vocabulary

When your output names a domain concept (an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `GLOSSARY.md`. Don't drift to synonyms the glossary avoids.

If the concept you need isn't in the glossary yet, that's a signal: either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0001 (ticket CLI in Python), but worth reopening because…_
