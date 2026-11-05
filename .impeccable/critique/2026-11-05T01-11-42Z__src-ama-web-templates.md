---
target: all built UI (v1)
total_score: 26
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 2
target_identity: "file:C:\\ama\\src\\ama\\web\\templates"
timestamp: 2026-11-05T01-11-42Z
slug: src-ama-web-templates
---
# Critique: built v1 UI (src/ama/web/templates) — 26/40

Scores: H1 3, H2 3, H3 2, H4 2, H5 3, H6 3, H7 1, H8 3, H9 3, H10 3.

Specificity: strongly authored (stage tabs, one sticker, drive cell, household copy); "colour = stage" grammar eroding (cobalt Titles bin on Filed film partials/rip.html:9, teal CD bins cd_rip.html:22,60, tomato "Selected" review_cd.html:38, non-Phase stickers).

Detector: 44 findings, all false positives (CSS not loaded in jsdom; Archivo Narrow parse). Real via overlay: 10px a.src chips ama.css:287.

## Priority issues
- [P1] Unguarded destructive/duplicate actions: Discard and re-rip (review_cd.html:20) no confirm; Try again == Dismiss (disc_failed.html:15, cd_failed.html:16-17). Fix: inline alertdialog; single "OK, I'll put it back in".
- [P1] Live regions: drive card aria-live re-announces every tick (now.html:10); new Review not announced; nav Review count never updates (base.html:17); #summary silent (review_movie.html:54).
- [P2] Weak ending + History can't audit filing: redirect to /review, no confirmation; filed film shows all Titles "Ripped" in cobalt; set siblings identical (history_row.html:10).
- [P2] Contrast/targets: ink-3 3.7-4.0:1 (.wait ama.css:187); scratch link 17px, a.src 18px, summaries 19-38px, links inside <summary> (history_row.html:19).
- [P3] Scratch page contradiction (partials/scratch.html:29 vs 36-45); idle phone stacks four empty bins.

## Persona red flags
- Owner: no shortcuts, no next-Review, no menu (Settings/Logs/Pause/Theme), TV select per Title.
- Sam: no h1, bin tabs are divs, no role=progressbar, no skip link, frame alts inside labels.
- Household: AccurateRip jargon in red with Accept/Discard choice; "It's TV episodes" buried.

## Minor
FILED sticker on every History row; mustard bar 1.9:1; Now tab current on /scratch; login inline styles; movie submit enabled with no Title.
