import shutil

from ama.db import MIGRATIONS, Database


def test_values_persist_across_restarts(tmp_path):
    path = tmp_path / "ama.sqlite3"
    db = Database(path)
    db.set_value("k", "v1")
    db.close()
    db = Database(path)  # second open re-runs migrations: must be a no-op
    assert db.get_value("k") == "v1"
    assert db.get_value("missing") is None


def test_new_migrations_apply_once_to_an_existing_database(tmp_path):
    mig = tmp_path / "migrations"
    mig.mkdir()
    (mig / "0001_a.sql").write_text("CREATE TABLE a (x INTEGER);")
    db = Database(tmp_path / "s.db", migrations=mig)
    db.execute("INSERT INTO a VALUES (1)")
    db.close()

    (mig / "0002_b.sql").write_text("ALTER TABLE a ADD COLUMN y TEXT DEFAULT 'z';")
    db = Database(tmp_path / "s.db", migrations=mig)
    db.close()
    db = Database(tmp_path / "s.db", migrations=mig)
    assert db.execute("SELECT x, y FROM a").fetchall() == [(1, "z")]


def test_a_failing_migration_leaves_the_database_unchanged(tmp_path):
    mig = tmp_path / "migrations"
    mig.mkdir()
    (mig / "0001_a.sql").write_text("CREATE TABLE a (x INTEGER);")
    Database(tmp_path / "s.db", migrations=mig).close()
    (mig / "0002_bad.sql").write_text("CREATE TABLE b (x INTEGER); SELECT nonsense FROM nowhere;")
    try:
        Database(tmp_path / "s.db", migrations=mig)
    except Exception:
        pass
    else:
        raise AssertionError("bad migration should fail")
    (mig / "0002_bad.sql").write_text("CREATE TABLE b (x INTEGER);")
    db = Database(tmp_path / "s.db", migrations=mig)  # retry converges
    assert db.execute("SELECT count(*) FROM b").fetchone() == (0,)


def test_a_v1_database_is_recreated_with_jobs_and_its_rows_dropped(tmp_path):
    v1 = tmp_path / "v1"
    v1.mkdir()
    for f in sorted(MIGRATIONS.glob("*.sql")):
        if int(f.name[:4]) <= 12:
            shutil.copy(f, v1 / f.name)
    db = Database(tmp_path / "s.db", migrations=v1)
    db.set_value("secret", "kept")
    db.execute("INSERT INTO discs (disc_type, status, scratch_dir, started_at) "
               "VALUES ('CD', 'ripped', 'x', '2026-11-04T10:00:00')")
    db.execute("INSERT INTO disc_log (disc_id, at, text) VALUES (1, '2026-11-04T10:00:00', 'hi')")
    db.close()

    db = Database(tmp_path / "s.db")
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
              .fetchall()}
    assert "discs" not in tables and "disc_log" not in tables
    assert db.execute("SELECT count(*) FROM jobs").fetchone() == (0,)
    assert db.execute("SELECT count(*) FROM job_log").fetchone() == (0,)
    assert db.get_value("secret") == "kept"
    assert db.execute("PRAGMA foreign_keys").fetchone() == (1,)


def test_a_new_database_has_the_same_schema_as_a_recreated_v1_one(tmp_path):
    v1 = tmp_path / "v1"
    v1.mkdir()
    for f in sorted(MIGRATIONS.glob("*.sql")):
        if int(f.name[:4]) <= 12:
            shutil.copy(f, v1 / f.name)
    Database(tmp_path / "old.db", migrations=v1).close()

    def schema(db: Database) -> list:
        return db.execute("SELECT type, name, sql FROM sqlite_master ORDER BY name").fetchall()

    assert schema(Database(tmp_path / "old.db")) == schema(Database(tmp_path / "new.db"))
