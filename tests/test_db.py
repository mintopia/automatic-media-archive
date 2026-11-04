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


def test_rebuilding_the_discs_table_keeps_every_discs_log_and_tracks(tmp_path):
    early = tmp_path / "early"
    early.mkdir()
    for f in sorted(MIGRATIONS.glob("000[1-4]_*.sql")):
        shutil.copy(f, early / f.name)
    db = Database(tmp_path / "s.db", migrations=early)
    db.execute("INSERT INTO discs (disc_type, status, scratch_dir, started_at) "
               "VALUES ('CD', 'ripped', 'x', '2026-11-04T10:00:00')")
    db.execute("INSERT INTO disc_log (disc_id, at, text) VALUES (1, '2026-11-04T10:00:00', 'hi')")
    db.execute("INSERT INTO cd_tracks (disc_id, number, seconds) VALUES (1, 1, 60.0)")
    db.close()

    db = Database(tmp_path / "s.db")
    assert db.execute("SELECT text FROM disc_log").fetchall() == [("hi",)]
    assert db.execute("SELECT number FROM cd_tracks").fetchall() == [(1,)]
    db.execute("UPDATE discs SET status = 'filed' WHERE id = 1")
    assert db.execute("PRAGMA foreign_keys").fetchone() == (1,)
