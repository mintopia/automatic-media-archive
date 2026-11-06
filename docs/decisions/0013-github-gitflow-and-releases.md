# Decision: Code lives on GitHub, branched with gitflow; issues stay on Forgejo for now

Status: accepted
Date: 2026-11-06

## Context
AMA is going public. Until now it lived on a private Forgejo (`git.mintopia.net`), with work merged straight into `develop`. A public project needs CI, tagged releases and a place people can reach.

## Decision
- **GitHub (`mintopia/automatic-media-archive`) is the canonical code remote**, named `origin`. The Forgejo remote is renamed `forgejo` and kept as a mirror. Nobody pushes to it by hand.
- **Issues stay on Forgejo for now.** GitHub Issues are disabled until the planned switch. Commits and PR bodies cite Forgejo issues by full URL, never by a bare `#n`, which GitHub would link to its own tracker.
- **Gitflow without release branches:**
  - Features: `feature/*` branches merge into `develop`. Small changes may be committed directly to `develop`.
  - Releases: a PR from `develop` to `main` runs CI (lint and tests). Once merged, a semver tag `vX.Y.Z` on `main` drives the release. `main` is then back-merged into `develop`.
  - Hotfixes: `hotfix/*` branches from `main` follow the same PR/tag route, and are back-merged into `develop`.
- `AGENTS.md` documents this flow for agents.

## Consequences
- `main` only ever holds released code. `develop` is the integration branch and the GitHub default.
- Every release is a tag on `main`, so "what's released" is unambiguous.
- Two hosts until the issue switch. A follow-up ADR records the move of issues to GitHub.

## Supersedes
None
