-- Small app-level values (e.g. the session signing secret).
CREATE TABLE kv (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
