# Issue tracker: Forgejo

Issues and specs for this repo live as **Forgejo issues** on the self-hosted
instance at `git.mintopia.net`, repo `mintopia/automatic-media-archive`. There is no `gh`/`glab`
and no `tea` CLI here, so operations go through the **Forgejo REST API** (Gitea
API v1 compatible).

## Setup for every session

Credentials live in `~/.forgejo` (`FORGEJO_BASE_URL`, `FORGEJO_USERNAME`,
`FORGEJO_API_KEY`). Source them rather than echoing the key:

```sh
set -a; . ~/.forgejo; set +a
API="$FORGEJO_BASE_URL/api/v1"
REPO="mintopia/automatic-media-archive"                 # owner/repo — infer from `git remote -v`
AUTH="Authorization: token $FORGEJO_API_KEY"
```

Issues are referenced by their per-repo **index** (`#<index>`). As on GitHub,
issues and pull requests share one index space.

## Conventions

- **Create an issue**: `curl -sS -X POST -H "$AUTH" -H 'Content-Type: application/json' "$API/repos/$REPO/issues" -d @- <<'JSON'` with `{"title":"...","body":"...","labels":[<id>,...]}`. Labels are given by **numeric id**, not name — resolve names first (see **Labels**). Use a heredoc for multi-line bodies.
- **Read an issue**: `curl -sS -H "$AUTH" "$API/repos/$REPO/issues/<index>"`; comments: `GET "$API/repos/$REPO/issues/<index>/comments"`.
- **List issues**: `curl -sS -H "$AUTH" "$API/repos/$REPO/issues?type=issues&state=open&labels=ready-for-agent"`. `type=issues` excludes PRs; `labels=` takes comma-separated **names**; `state` is `open`/`closed`/`all`.
- **Comment**: `POST "$API/repos/$REPO/issues/<index>/comments"` with `{"body":"..."}`.
- **Labels**: resolve names→ids with `curl -sS -H "$AUTH" "$API/repos/$REPO/labels?limit=100"`. Add: `POST "$API/repos/$REPO/issues/<index>/labels"` with `{"labels":[<id>,...]}`. Remove: `DELETE "$API/repos/$REPO/issues/<index>/labels/<id>"`.
- **Close**: post the explanation as a comment, then `PATCH "$API/repos/$REPO/issues/<index>"` with `{"state":"closed"}` (`"open"` to reopen).
- **Assign (claim)**: `POST "$API/repos/$REPO/issues/<index>/assignees"` with `{"assignees":["'$FORGEJO_USERNAME'"]}`.
- **Sub-issue of a parent**: Forgejo has no GitHub-style native sub-issues. Add the child to a task list (`- [ ] #<child>`) in the parent body and put `Part of #<parent>` at the top of the child body.
- **Blocking**: Forgejo **issue dependencies**. Mark that `<child>` depends on `<blocker>`: `POST "$API/repos/$REPO/issues/<child>/dependencies"` with `{"index":<blocker>,"owner":"<owner>","repo":"<repo>"}` (without `owner`/`repo` it returns 404). List a ticket's blockers: `GET "$API/repos/$REPO/issues/<child>/dependencies"`. Remove: `DELETE "$API/repos/$REPO/issues/<child>/dependencies"` with `{"index":<blocker>}`. A ticket is **unblocked** when every dependency issue is closed. If dependencies are disabled on the instance, fall back to a `Blocked by: #<n>, #<n>` line at the top of the child body.
- **Count open blockers**: `GET "$API/repos/$REPO/issues/<index>/dependencies"` and count entries whose `state` is `open` (0 ⇒ startable).

Infer `REPO` from `git remote -v` (the path after the host). File issues only
into this repo; never into the upstream these skills came from.

## Pull requests as a triage surface

**PRs as a request surface: no.** _(Set to `yes` if this repo treats external PRs as feature requests; `/triage` reads this flag.)_

If set to `yes`, run PRs through the same labels/states using the Forgejo pulls
API: list with `GET "$API/repos/$REPO/pulls?state=open"`, read with
`GET "$API/repos/$REPO/pulls/<index>"` and its `.diff_url`, and comment/label/
close via the shared issue endpoints above (a PR's `<index>` is also an issue
index).

## When a skill says "publish to the issue tracker"

Create a Forgejo issue (see **Create an issue**).

## When a skill says "fetch the relevant ticket"

Read it as in **Read an issue** above.

## Ticket CLI (batch creation for a piece of work)

To create the tickets for one piece of work, prefer `bin/tickets.py` over
hand-rolled API calls — it enforces the project's invariants:

- epics are **milestones**; every ticket in the plan is created under that milestone;
- blockers are wired as real Forgejo **dependencies**;
- `ready-for-agent` is applied **last**, only after milestone + blockers are confirmed in place;
- **no circular blocker dependencies** (ticket-level or epic-level) — rejected before any writes.

```sh
bin/tickets.py validate plan.json           # dry-run: schema + cycle checks, no writes
bin/tickets.py apply    plan.json            # create milestone, issues, blockers, then ready labels
```

The plan is a JSON file: an `epic` (→ milestone) and `tickets[]` with
`id`/`title`/`body`, optional `blocked_by` (local ids or existing `#numbers`),
`labels`, `assignees`, and `ready` (`agent` default / `human` / `none`). See
`examples/tickets.plan.json`. Not idempotent — re-running creates duplicates.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a single issue with its tickets as linked
children.

- **Map**: one issue labelled `wayfinder:map`, holding the Notes / Decisions-so-far / Fog body.
- **Child ticket**: an issue linked from the map via a task list (`- [ ] #<child>`) with `Part of #<map>` at the top of its body. Labels: `wayfinder:<type>` (`research`/`prototype`/`grilling`/`task`). Once claimed, assign it to the driving dev.
- **Blocking**: see **Blocking** under Conventions.
- **Frontier query**: list the map's open children, drop any with an open blocker or an assignee; first in map order wins.
- **Claim**: assign yourself (see **Assign**), the session's first write.
- **Resolve**: comment the answer, close the issue, then append a context pointer to the map's Decisions-so-far.

(The `wayfinder:*` and `wayfinder:map` labels are created on first use — same
`POST .../labels` as the triage labels.)
