# Automatic Media Archive

## Code hosting and branches

Code lives on GitHub (`mintopia/automatic-media-archive`), the `origin` remote.
The Forgejo repo on git.mintopia.net is a mirror of it, the `forgejo` remote:
never push to it. Issues stay on Forgejo (below); GitHub Issues are off (ADR 0013).

Gitflow without release branches. See `CONTRIBUTING.md` for the steps.

- Features: branch `feature/*` from `develop` and merge it back into `develop`.
  Small changes may go straight onto `develop`.
- Releases: a PR from `develop` to `main`, which runs CI; once merged, tag `main`
  `vX.Y.Z`, then back-merge `main` into `develop`.
- Hotfixes: branch `hotfix/*` from `main`, PR it into `main`, tag `vX.Y.Z`, then
  back-merge `main` into `develop`.
- `main` only holds released code. Never commit to it directly.
- Cite issues in commits and PR bodies by full Forgejo URL
  (`https://git.mintopia.net/mintopia/automatic-media-archive/issues/<n>`), never a
  bare `#<n>`: GitHub would link that to its own tracker.

## Agent skills

### Issue tracker

Issues are tracked as Forgejo issues (`mintopia/automatic-media-archive` on
git.mintopia.net), driven through the Forgejo REST API; epics are milestones,
batch-created with `bin/tickets.py`. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical triage labels (`needs-triage`, `needs-info`,
`ready-for-agent`, `ready-for-human`, `wontfix`), created in the repo. See
`docs/agents/triage-labels.md`.

### Domain docs

Single-context: `GLOSSARY.md` at the root and ADRs in `docs/decisions/`. See
`docs/agents/domain.md`.
