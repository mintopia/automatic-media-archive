# Decision: Ticket CLI in Python (stdlib), driven by a declarative plan file

Status: accepted
Date: 2026-11-04

## Context
Tickets are created in Forgejo with strict invariants: epics as milestones,
every ticket tied to its epic, blockers set in the tracker, `ready-for-agent`
applied only after relationships and blockers exist, and no circular blocker
dependencies (including between epics). The same tooling is already proven in
the `as204776/ipam` repo.

## Decision
Use `bin/tickets.py` (copied from ipam): Python 3 standard library only, driven
by a declarative JSON plan file. `validate` checks schema + cycles; `apply`
creates the milestone, issues, blocker dependencies, then ready labels last.
Talks to Forgejo via REST using `~/.forgejo` creds (see
`docs/agents/issue-tracker.md`).

## Consequences
- Zero dependencies; runnable anywhere Python 3 exists.
- Invariants enforced in one place against one input.
- Not idempotent: re-running a plan creates duplicates.
- Copy of ipam's script; fixes must be ported between repos manually.

## Supersedes
None
