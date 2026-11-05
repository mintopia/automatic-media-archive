-- v2 (#34): configurable log pruning. A Step whose output was removed (`logs.keep_days`)
-- keeps its row and says when its output went, and after how many days.
ALTER TABLE steps ADD COLUMN output_removed_at TEXT;      -- ISO 8601, local time
ALTER TABLE steps ADD COLUMN output_kept_days  INTEGER;   -- the keep_days that removed it
