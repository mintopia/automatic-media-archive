#!/usr/bin/env python3
"""Create Forgejo tickets for a piece of work from a declarative plan.

Enforces the project's ticket invariants:
  1. epics are milestones
  2. every ticket is tied to its epic milestone
  3. blockers are real tracker dependencies
  4. `ready-for-agent` is applied only after milestone + blockers are wired
  5. no circular blocker dependencies (ticket-level or epic-level)

Usage:
  bin/tickets.py apply plan.json [--dry-run] [--repo owner/repo]
  bin/tickets.py validate plan.json           # alias for apply --dry-run

Config comes from ~/.forgejo (FORGEJO_BASE_URL, FORGEJO_USERNAME,
FORGEJO_API_KEY); repo is inferred from `git remote get-url origin`.

Plan file (JSON):
{
  "epic": {"title": "...", "description": "...", "due_on": "2026-12-01"},
  "tickets": [
    {"id": "schema", "title": "...", "body": "..." | ["line", "line"],
     "ready": "agent" | "human" | "none",      # default "agent"
     "labels": ["extra-label"], "assignees": ["user"],
     "blocked_by": ["other-local-id", "#42"]}  # local ids or existing #numbers
  ]
}
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

READY_AGENT = "ready-for-agent"
READY_HUMAN = "ready-for-human"


# ---------- config ----------

def load_env(path="~/.forgejo"):
    env = {}
    p = os.path.expanduser(path)
    if not os.path.exists(p):
        die(f"missing {path} (needs FORGEJO_BASE_URL, FORGEJO_USERNAME, FORGEJO_API_KEY)")
    with open(p) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    for k in ("FORGEJO_BASE_URL", "FORGEJO_API_KEY"):
        if not env.get(k):
            die(f"{k} not set in {path}")
    return env


def infer_repo():
    try:
        url = subprocess.check_output(
            ["git", "remote", "get-url", "origin"], text=True
        ).strip()
    except Exception:
        die("could not read git remote 'origin'; pass --repo owner/repo")
    m = re.search(r"[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
    if not m:
        die(f"could not parse owner/repo from remote: {url}")
    return m.group(1)


# ---------- api ----------

class Forgejo:
    def __init__(self, base, token, repo):
        self.api = base.rstrip("/") + "/api/v1"
        self.token = token
        self.repo = repo
        self._labels = None

    def _req(self, method, path, body=None):
        url = self.api + path
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", "token " + self.token)
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req) as r:
                raw = r.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            die(f"{method} {path} -> HTTP {e.code}: {e.read().decode(errors='replace')[:300]}")

    def labels(self):
        if self._labels is None:
            rows = self._req("GET", f"/repos/{self.repo}/labels?limit=100") or []
            self._labels = {l["name"]: l["id"] for l in rows}
        return self._labels

    def label_id(self, name):
        lid = self.labels().get(name)
        if lid is None:
            die(f"label '{name}' not found in {self.repo}; create it first")
        return lid

    def create_milestone(self, title, description="", due_on=None):
        body = {"title": title, "description": description or ""}
        if due_on:
            body["due_on"] = due_on + ("" if "T" in due_on else "T00:00:00Z")
        return self._req("POST", f"/repos/{self.repo}/milestones", body)

    def create_issue(self, title, body, milestone_id, label_ids, assignees):
        payload = {"title": title, "body": body, "milestone": milestone_id}
        if label_ids:
            payload["labels"] = label_ids
        if assignees:
            payload["assignees"] = assignees
        return self._req("POST", f"/repos/{self.repo}/issues", payload)

    def get_issue(self, index):
        return self._req("GET", f"/repos/{self.repo}/issues/{index}")

    def add_dependency(self, index, blocker_index):
        owner, name = self.repo.split("/", 1)
        return self._req("POST", f"/repos/{self.repo}/issues/{index}/dependencies",
                          {"index": blocker_index, "owner": owner, "repo": name})

    def list_dependencies(self, index):
        return self._req("GET", f"/repos/{self.repo}/issues/{index}/dependencies") or []

    def add_label(self, index, label_id):
        return self._req("POST", f"/repos/{self.repo}/issues/{index}/labels",
                          {"labels": [label_id]})


# ---------- graph / cycles ----------

def find_cycle(edges):
    """edges: dict node -> iterable of nodes it depends on. Returns a cycle
    path [a, b, ..., a] if one exists, else None."""
    WHITE, GREY, BLACK = 0, 1, 2
    color = {}
    stack = []

    def visit(n):
        color[n] = GREY
        stack.append(n)
        for m in edges.get(n, ()):
            if color.get(m, WHITE) == GREY:
                return stack[stack.index(m):] + [m]
            if color.get(m, WHITE) == WHITE:
                c = visit(m)
                if c:
                    return c
        stack.pop()
        color[n] = BLACK
        return None

    for n in list(edges):
        if color.get(n, WHITE) == WHITE:
            c = visit(n)
            if c:
                return c
    return None


# ---------- plan ----------

def body_text(b):
    if isinstance(b, list):
        return "\n".join(b)
    return b or ""


def load_plan(path):
    try:
        with open(path) as f:
            plan = json.load(f)
    except Exception as e:
        die(f"could not read plan {path}: {e}")
    epic = plan.get("epic") or {}
    if not epic.get("title"):
        die("plan.epic.title is required")
    tickets = plan.get("tickets") or []
    if not tickets:
        die("plan.tickets is empty")
    ids = [t.get("id") for t in tickets]
    if any(not i for i in ids):
        die("every ticket needs a unique 'id'")
    if len(set(ids)) != len(ids):
        die("ticket ids must be unique")
    idset = set(ids)
    for t in tickets:
        if not t.get("title"):
            die(f"ticket '{t['id']}' needs a title")
        if t.get("ready", "agent") not in ("agent", "human", "none"):
            die(f"ticket '{t['id']}': ready must be agent|human|none")
        for b in t.get("blocked_by", []):
            if not (b in idset or re.fullmatch(r"#\d+", str(b))):
                die(f"ticket '{t['id']}' blocked_by '{b}' is not a known local id or #number")
    return epic, tickets


def check_cycles(fj, tickets, epic=None):
    """Build the depends-on graph across plan tickets + reachable existing
    issues, and reject ticket-level or epic-level cycles. Plan ticket nodes are
    their local ids; existing issues are '#<n>'."""
    edges = {}          # node -> set(blockers)
    epic_of = {}        # node -> epic key
    for t in tickets:
        edges.setdefault(t["id"], set())
        epic_of[t["id"]] = f"ms:{epic['milestone_id']}" if epic and epic.get("milestone_id") else "epic:new"

    # existing issues referenced as blockers: walk their dependency graph
    seen = set()
    frontier = [str(b) for t in tickets for b in t.get("blocked_by", [])
                if re.fullmatch(r"#\d+", str(b))]
    for t in tickets:
        for b in t.get("blocked_by", []):
            edges[t["id"]].add("#" + str(b).lstrip("#") if re.fullmatch(r"#\d+", str(b))
                               else b)
    while frontier:
        ref = frontier.pop()
        n = str(int(ref.lstrip("#")))
        key = "#" + n
        if key in seen:
            continue
        seen.add(key)
        issue = fj.get_issue(n)
        ms = issue.get("milestone")
        epic_of[key] = f"ms:{ms['id']}" if ms else f"noms:{n}"
        deps = fj.list_dependencies(n)
        blockers = {"#" + str(d["number"]) for d in deps}
        edges.setdefault(key, set()).update(blockers)
        for bk in blockers:
            if bk not in seen:
                frontier.append(bk)

    cyc = find_cycle(edges)
    if cyc:
        die("circular blocker dependency: " + " -> ".join(cyc))

    # epic-level: collapse to epic keys, drop self-edges
    ep_edges = {}
    for n, bs in edges.items():
        en = epic_of.get(n, "unknown")
        for b in bs:
            eb = epic_of.get(b, "unknown")
            if en != eb:
                ep_edges.setdefault(en, set()).add(eb)
    cyc = find_cycle(ep_edges)
    if cyc:
        die("circular blocker dependency between epics: " + " -> ".join(cyc))


# ---------- apply ----------

def apply(plan_path, dry_run, repo_override):
    env = load_env()
    repo = repo_override or infer_repo()
    fj = Forgejo(env["FORGEJO_BASE_URL"], env["FORGEJO_API_KEY"], repo)
    epic, tickets = load_plan(plan_path)

    # resolve labels up front so a missing one fails before any writes
    fj.label_id(READY_AGENT)
    fj.label_id(READY_HUMAN)
    for t in tickets:
        for name in t.get("labels", []):
            fj.label_id(name)

    check_cycles(fj, tickets, epic)

    if dry_run:
        print(f"[dry-run] repo {repo}")
        print(f"[dry-run] epic (milestone): {epic['title']}")
        for t in tickets:
            ready = t.get("ready", "agent")
            blk = ", ".join(str(b) for b in t.get("blocked_by", [])) or "-"
            print(f"[dry-run]   ticket {t['id']}: {t['title']}  "
                  f"[ready={ready}] blocked_by={blk}")
        print("[dry-run] validation passed (schema + no cycles). No changes made.")
        return

    # 1. epic milestone
    # epic.milestone_id = add to an existing milestone instead of creating one
    ms = ({"id": epic["milestone_id"], "title": epic["title"]} if epic.get("milestone_id")
          else fj.create_milestone(epic["title"], epic.get("description", ""), epic.get("due_on")))
    print(f"milestone #{ms['id']}: {ms['title']}")

    # 2. create issues under the milestone (ready-* applied later, step 4)
    index_of = {}
    for t in tickets:
        label_ids = [fj.label_id(n) for n in t.get("labels", [])]
        issue = fj.create_issue(t["title"], body_text(t.get("body")), ms["id"],
                                 label_ids, t.get("assignees", []))
        index_of[t["id"]] = issue["number"]
        print(f"  #{issue['number']}: {t['title']}")

    # 3. wire blocker dependencies
    def resolve(ref):
        ref = str(ref)
        return int(ref.lstrip("#")) if ref.startswith("#") else index_of[ref]

    for t in tickets:
        for b in t.get("blocked_by", []):
            fj.add_dependency(index_of[t["id"]], resolve(b))
            print(f"  #{index_of[t['id']]} blocked-by #{resolve(b)}")

    # 4. ready label LAST, only after verifying milestone + blockers are set
    for t in tickets:
        ready = t.get("ready", "agent")
        if ready == "none":
            continue
        idx = index_of[t["id"]]
        issue = fj.get_issue(idx)
        if not issue.get("milestone"):
            die(f"#{idx} has no milestone; refusing to mark ready")
        want = {resolve(b) for b in t.get("blocked_by", [])}
        have = {d["number"] for d in fj.list_dependencies(idx)}
        if not want <= have:
            die(f"#{idx} missing blockers {want - have}; refusing to mark ready")
        fj.add_label(idx, fj.label_id(READY_AGENT if ready == "agent" else READY_HUMAN))
        print(f"  #{idx} -> {'ready-for-agent' if ready == 'agent' else 'ready-for-human'}")

    print(f"done: epic milestone #{ms['id']} with {len(tickets)} tickets")


def die(msg):
    print("error: " + msg, file=sys.stderr)
    sys.exit(1)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Create Forgejo tickets from a plan.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pa = sub.add_parser("apply", help="create tickets from a plan")
    pa.add_argument("plan")
    pa.add_argument("--dry-run", action="store_true")
    pa.add_argument("--repo", help="owner/repo (default: from git remote)")
    pv = sub.add_parser("validate", help="validate a plan without writing")
    pv.add_argument("plan")
    pv.add_argument("--repo")
    args = ap.parse_args(argv)
    if args.cmd == "validate":
        apply(args.plan, True, args.repo)
    else:
        apply(args.plan, args.dry_run, args.repo)


if __name__ == "__main__":
    main()
