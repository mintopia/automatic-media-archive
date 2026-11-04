# Automatic Media Archive

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
