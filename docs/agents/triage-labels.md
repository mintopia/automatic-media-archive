# Triage Labels

The skills speak in terms of five canonical triage roles. This file maps those roles to the actual label strings used in this repo's issue tracker (Forgejo, `mintopia/automatic-media-archive`). All five exist in the repo.

| Canonical role    | Label in our tracker | Meaning                                  |
| ----------------- | -------------------- | ---------------------------------------- |
| `needs-triage`    | `needs-triage`       | Maintainer needs to evaluate this issue  |
| `needs-info`      | `needs-info`         | Waiting on reporter for more information |
| `ready-for-agent` | `ready-for-agent`    | Fully specified, ready for an AFK agent  |
| `ready-for-human` | `ready-for-human`    | Requires human implementation            |
| `wontfix`         | `wontfix`            | Will not be actioned                     |

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), use the corresponding label string from this table.

Forgejo's label API applies labels by numeric id, not name — resolve the id
from the name via `GET /repos/mintopia/automatic-media-archive/labels` (see
`docs/agents/issue-tracker.md` → **Labels**).

Edit the "Label in our tracker" column if you change the vocabulary.
