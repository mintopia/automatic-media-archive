-- The minimum Title length a video Rip used (ADR 0005); older Jobs used 30 s.
ALTER TABLE jobs ADD COLUMN min_title_seconds INTEGER NOT NULL DEFAULT 30;
