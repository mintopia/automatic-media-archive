"""Setup's steps: one module each, exposing `STEP` (an `ama.setup.Step`).

Steps run in `Step.order` (ADR 0016's order). Numbers in use or kept for a step:
10 welcome, 20 drive and MakeMKV, 30 where things go, 40 TMDB key,
50 reach AMA from other devices, 90 ready (always last: it writes the file).
"""
