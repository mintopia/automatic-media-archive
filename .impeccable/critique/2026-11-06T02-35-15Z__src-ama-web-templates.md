---
target: everything (built web UI)
total_score: 30
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 2
target_identity: "file:C:\\ama\\src\\ama\\web\\templates"
timestamp: 2026-11-06T02-35-15Z
slug: src-ama-web-templates
---
# Critique: built web UI (src/ama/web/templates) — 30/40

Method: dual-agent (A: critique-A · B: critique-B). Live on an isolated copy at :8091, light + dark, 1387px + 390px.

## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 3 | "Didn't work" bin says "Nothing has failed" beside a DVD failure notice |
| 2 | Match System / Real World | 3 | Raw strings leak: "Q: is not an optical drive", `OCEANS_ELEVEN - Title 3`, "TMDB 161", MB UUID |
| 3 | User Control and Freedom | 3 | Good exits; no recovery for partially failed Encodes |
| 4 | Consistency and Standards | 3 | Job page "x / Won't run" vs Logs "alert / Didn't run"; "Not kept" = skipped AND failed |
| 5 | Error Prevention | 3 | Saved bad Address (127.0.0.1) shows no warning |
| 6 | Recognition Rather Than Recall | 3 | TV mapping: one long episode select per Title |
| 7 | Flexibility and Efficiency | 2 | No next-Review, no shortcuts, no "fill episodes in order" |
| 8 | Aesthetic and Minimalist Design | 4 | Calm, printed, thesis held; dark mode complete |
| 9 | Error Recovery | 3 | Failure page exemplary; partial Encode failure has no path |
| 10 | Help and Documentation | 3 | Inline hints and "You probably don't need this" Advanced groups |
| **Total** | | **30/40** | **Good** |

## Design Specificity Verdict

LLM: Authored, not interchangeable. Die-cut stage tabs, 3px stage-colour sheet tops, dark drive cell as largest object, one price-gun sticker per Disc, outline-only Failed, Archivo Narrow only on tabs, hairline-built flat surfaces. Prior colour drift (Filed Titles/CD Tracks, tomato "Selected") is fixed. The weakness is truthfulness, not look: Now can contradict itself and FILED can hide failed Encodes.

Deterministic scan: `detect` on templates exited 2 with 78 findings, all at line 0 and essentially all false positives (72 design-system-color + 3 low-contrast from unresolved stylesheet = default black; 2 cramped-padding in base.html menu `<details>` / `div.segs` not reproduced live; 1 design-system-font for Archivo Narrow brand, sanctioned by DESIGN.md). Live overlay on `/`, `/history`, `/jobs/2`, `/settings/general`: 0. `/logs`: 1 real — search placeholder #7c8087 on #fff = 4.0:1 (< 4.5:1); the muted placeholder token likely affects every placeholder. Dark mode not scanned by the overlay.

## Priority Issues

- **[P1] "Didn't work" bin only knows about CDs.** `web/__init__.py:135` feeds `cd.jobs(JobStatus.FAILED)`; `partials/rip_failed.html:9` prints "Nothing has failed" while FIREFLY_DISC1 (DVD) failed twice (/jobs/3, /jobs/4). Drive notice (`partials/drive.html:47-54`) shows only the latest, so Job 3 is unreachable from Now; fallback label says "Unknown CD" for any type. Breaks Principle 1. Fix: feed all undismissed failed Jobs (every Disc Type) into the bin, fallback "Unknown {disc type}". Command: harden.
- **[P1] FILED hides failed Encodes.** /jobs/2 wears teal FILED, History says "6 Extras", Titles 3–5 "Not kept", steps say "Failed after 8 h 11 min". "Not kept" means both chosen-skip and lost-to-failure. Breaks Principle 3. Fix: distinct "Encode failed" Filed-as value, attention notice on the Job page with Retry / Leave them out, count on the History row (`partials/history_row.html:23`). Command: harden + clarify.
- **[P2] CD Review asks two questions at once.** `review_cd.html:19-73`: Keep/Discard-and-re-rip above edition radios, manual entry and File — 5+ options, two decisions. Breaks Principle 4. Fix: settle verification first, then show editions (or demote verification to a note under the edition question). Command: distill.
- **[P2] Raw identifiers in the household view.** `partials/drive.html:31` prints `drive.reason` verbatim; Extras default to `OCEANS_ELEVEN - Title N`; Job page Identification shows "TMDB 161" and an MB UUID. Fix: map drive reasons to plain sentences (raw to Logs), default Extra names "<Film>: Extra N", move ids into About this Disc. Command: clarify.
- **[P3] Movie Review alternatives scattered.** `review_movie.html:66-73` puts "It's TV episodes" in a separate "Not a film?" block; mockup puts it beside "Encode and file"; 6+ actions visible. Fix: follow the mockup; Extras Disc as secondary text link. Command: layout.

## Persona Red Flags

- **Alex (power user):** no next-Review action or shortcuts; TV mapping one select per Title; partial Encode failures not retryable from UI.
- **Sam (keyboard/SR):** each Review row has two links to different places (`partials/review_bin.html:6`), announced twice; "Same length" is visual-only; failure iconography/wording differs Job vs Logs (`job_steps.html:3` vs `run_step.html:3`).
- **Casey (phone at the drive):** no horizontal scroll, main controls 44–48px, but History title links 16px tall, "Everything filed before" / "Sort the Extras" 14px, CD source links 20px.
- **Household member feeding Discs:** "Q: is not an optical drive" and "The app stopped during the Rip" read as alarms; FILED next to red x steps; CD Review mixes "trust the rip" with "which edition".

## Minor Observations

- /logs search placeholder 4.0:1 contrast (detector, real); check the shared placeholder token in both themes.
- Logs app run reads "Done" beside "10 error lines" — say "Done, with warnings".
- /jobs/3, /jobs/4 breadcrumb "Didn't work" is plain text, not a link.
- Saved Address 127.0.0.1 shows no `.fwarn`; only the unsaved-edit state warns.
- Settings › Encode: group "Encoder" repeats as field label "Encoder".
- App run step "Connect to the NAS" (/logs/runs/1) post-ADR 0011 — confirm it's a pre-ADR run.
- One SSE connection per page: ~6 tabs hits the HTTP/1.1 per-host limit and new pages hang.
- Dark mode: drive cell #24262A barely separates from sheet #1B1C1F.
- Extras-sorting thumbnails small on desktop.

## Questions to Consider

- Should "Filed" mean everything kept made it, with a distinct "Filed, with gaps" state?
- Should a missing or broken drive be the one state that turns the drive cell into an alert?
- Would TV Review be faster as "these Titles are Episodes 4–9 in order: confirm or adjust"?
