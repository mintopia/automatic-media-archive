"""SQLite state.

Schema changes are numbered SQL files in `ama/migrations/` (`NNNN_name.sql`).
On open, every file numbered above `PRAGMA user_version` runs in its own
transaction together with the version bump, so a failed migration leaves the
database at the previous version and a restart simply retries it.
Never edit a migration that has shipped; add a new one.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any

MIGRATIONS = Path(__file__).parent / "migrations"


class Database:
    """One shared connection, serialised by a lock (safe from threads and the loop)."""

    def __init__(self, path: Path, migrations: Path = MIGRATIONS) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._lock = threading.Lock()
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._migrate(migrations)

    def _migrate(self, migrations: Path) -> None:
        current = self._conn.execute("PRAGMA user_version").fetchone()[0]
        for f in sorted(migrations.glob("[0-9][0-9][0-9][0-9]_*.sql")):
            n = int(f.name[:4])
            if n <= current:
                continue
            try:
                self._conn.executescript(
                    f"BEGIN;\n{f.read_text(encoding='utf-8')}\n;PRAGMA user_version={n};\nCOMMIT;"
                )
            except sqlite3.Error as e:
                if self._conn.in_transaction:
                    self._conn.execute("ROLLBACK")
                raise RuntimeError(f"migration {f.name} failed: {e}") from e
            current = n

    def execute(self, sql: str, params: tuple[Any, ...] | dict[str, Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, params)

    def get_value(self, key: str) -> str | None:
        row = self.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set_value(self, key: str, value: str) -> None:
        self.execute(
            "INSERT INTO kv (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    def close(self) -> None:
        self._conn.close()
