-- Phase 3 (#55): the minimum Title length a video Rip used (ADR 0005), per Disc Type in
-- ama.toml. Jobs from before it was configurable used 30 s.
ALTER TABLE jobs ADD COLUMN min_title_seconds INTEGER NOT NULL DEFAULT 30;
