---
target: the UI
total_score: 24
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 3
target_identity: "file:C:\\ama\\src\\ama\\web\\templates"
timestamp: 2026-11-06T17-41-02Z
slug: src-ama-web-templates
---
# Critique: built web UI (src/ama/web/templates) — 24/40

Method: dual-agent (A: critique-A · B: critique-B). Live on seeded isolated copy at :8091. A saw phone width (500px, light+dark) live; desktop from source.

## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 3 | /jobs/4 puts Encode progress under Settings and Titles |
| 2 | Match System / Real World | 3 | `{tmdb-298}` paths, "+667 samples", "Specials (Season 00)" reach household |
| 3 | User Control and Freedom | 2 | "It's TV, not a film" one-tap POST, no confirm, 24px (partials/kind_mark.html) |
| 4 | Consistency and Standards | 2 | One Disc = "Ocean's Eleven (2001)" / "OCEANS_ELEVEN" / "OCEANS"; film Review has summary, TV doesn't |
| 5 | Error Prevention | 1 | Film Review pre-selects best guess even when reason is NO_MATCH; TV commit above question |
| 6 | Recognition Rather Than Recall | 3 | Frames at 10/50/90% excellent |
| 7 | Flexibility and Efficiency | 2 | 4 × 17-option episode selects, no auto-assign or shortcuts |
| 8 | Aesthetic and Minimalist Design | 3 | Drive card carries 6 controls while ripping |
| 9 | Error Recovery | 2 | Settings with TOML unavailable: alert + "Saved to ama.toml" foot contradict |
| 10 | Help and Documentation | 3 | "Pictures are taken from the ripped copy" — right reassurance |
| **Total** | | **24/40** | **Acceptable** |

## Design Specificity Verdict
Strongly authored: Browser Bin metaphor (die-cut tabs, price-gun stickers, one colour per stage, one hairline) belongs only to AMA; dark mode complete. Problems are Review logic, not look.
Detector: 90 CLI findings (84 design-system-color, 3 low-contrast, 1 design-system-font, 2 cramped-padding), all line 0 and caused by the static scan not resolving `/static/ama.css` — false positives; cramped-padding on pause-menu `<details>` and `.segs` low-confidence. Live overlay: no anti-patterns on /, /review/3, /review/5, /history, /settings.

## Priority Issues
- **[P1] Film Review hides its own uncertainty.** movie_review_pages.py:145 pre-selects the best guess regardless of review_reason; review_movie.html shows no reason. Now says "Not in the film database (TMDB)", Review shows a confident "Best guess · Same length" and a live "Encode and file". Breaks Principle 3. Fix: reason notice above Likely films; don't pre-select when reason ∈ _FILM_UNSURE (review_items.py:82). Command: harden + clarify.
- **[P1] TV Review commit above the question, no consequence summary.** review_tv.html:13-16 "File episodes" in header; no "When you confirm"; guessed vs set rows indistinguishable; duplicate picks not caught pre-submit. Command: layout + harden.
- **[P1] One Disc, three names.** Label vs best guess varies across Now, Review bin, Logs, status sentence. Fix: one naming rule everywhere (best guess, or label marked Unidentified, "Disc OCEANS" as meta). Command: clarify.
- **[P2] Phone targets and mis-taps.** Row title links 16–18px tall (bins, history, ripping_bin.html:19), kind toggle 24px next to "Change the film", TMDB/MB chips 24px; ama.css:402-403 only expands `.hist .meta a`/`.src`. Fix: stretched-link rows; kind toggle behind details/confirm. Command: adapt.
- **[P2] Job page leads with settings not status.** /jobs/4 progress last. Fix: Steps bin under header. Command: layout.

## Persona Red Flags
- Alex: 17-option selects ×4, no auto-assign in order, no shortcuts.
- Sam: "Wrap lines" visible and focusable while output collapsed; check frame alt text and "Best guess" announcement on radios.
- Casey: 24px "It's TV, not a film" beside "Change the film" on rip card; accidental POST reclassifies Disc.
- Household reviewer: `{tmdb-298}`, "Same length", "Specials (Season 00)", "Drive read offset +667 samples".

## Minor Observations
- "Wrap lines" shown with output collapsed (rip card, Encoding row).
- Ripping bin repeats the drive Disc right under the drive panel on phone.
- Steps show "0 s" durations (/jobs/4).
- Inline styles review_tv.html:20,23,26,38,40.
- Filed page ending (/jobs/1) is settings + track table; no "It's in Plex: Music/Queen/Greatest Hits" moment.

## Questions to Consider
- If Review pre-fills everything, what is the human being asked? Would "Is this Ocean's Thirteen? Yes / No, search" be the one question?
- Should the drive card carry any identification controls, or stay read-only?
- What should the moment a Disc reaches Plex feel like?
