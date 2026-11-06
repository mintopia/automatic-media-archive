---
target: landing page
total_score: 23
max_score: 32
na_heuristics: 7,10
p0_count: 0
p1_count: 2
target_identity: "file:C:\\ama\\website\\src\\pages\\index.astro"
target_fingerprint: "sha256:2f09baf6915778074e8a12085b09c45d9e9b0dfb0d6d42864009de93e2ca6fc9"
target_path: "C:\\ama\\website\\src\\pages\\index.astro"
timestamp: 2026-11-06T12-36-01Z
slug: website-src-pages-index-astro
---
## Design Health Score
| # | Heuristic | Score | Key Issue |
|---|---|---|---|
| 1 | Visibility of System Status | 3 | App window shows live state; the promised waiting Disc is cut off |
| 2 | Match System / Real World | 3 | Plain language, real titles |
| 3 | User Control and Freedom | 3 | Anchors, skip link |
| 4 | Consistency and Standards | 2 | Two Download buttons behave differently; brand shown twice |
| 5 | Error Prevention | 3 | SmartScreen warning explained up front |
| 6 | Recognition Rather Than Recall | 3 | Stage names repeat in order |
| 7 | Flexibility and Efficiency | n/a | Landing page |
| 8 | Aesthetic and Minimalist Design | 3 | Restrained, but long with same-shaped sections |
| 9 | Error Recovery | 3 | Failure notification and log mentioned |
| 10 | Help and Documentation | n/a | Docs are a separate surface |
| Total | | 23/32 | Good |

## Design Specificity Verdict
Clearly authored for AMA: the framed Now page with real titles demonstrates the product. Below the hero, sections share one shape and read as a template. Detector: 5 findings, all false positives or minor (tight-leading on display h1, cramped-padding x2 inside the app frame, Archivo Narrow parse quirk, #9A9DA3 lite frame tone).

## Priority Issues
- [P1] Hero app window hides the Needs review row, the product's differentiator. Fix: show it above the fold (shorter drive panel or taller window). layout
- [P1] Hero Download for Windows jumps to #install while the top-bar Download goes to GitHub Releases. Fix: hero primary goes to the latest release. clarify
- [P2] Brand shown twice in the first viewport (site bar and framed app bar). Fix: drop the brand from the framed app bar. distill
- [P2] Six same-shaped sections; 6,200px phone page; gallery unreadable on phones. Fix: merge requirements into Install, trim the Disc types table, hide the gallery on phones, vary one section's scale. layout
- [P3] Stage colours as decorative rules on How a Disc flows weaken their meaning. quieter

## Persona Red Flags
- Jordan: the hero Download doesn't download.
- Casey: proof below the fold on phones; gallery too small; Install far down.
- Household member: HEVC/MKV/AccurateRip unexplained.

## Minor Observations
- Hero CTA column bottom-aligned leaves a void above it.
- The failed-rip alert uses the same icon as the needs-you alert.
- "For Discs you own." is low-key trailing small text.
- 1960 still colour is a literal, not a token.

## Questions to Consider
- Open the hero window on the Review question instead?
- Three sections instead of six?
- Should the first screen work for a household member too?
