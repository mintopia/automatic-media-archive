import shutil
from datetime import datetime

from ama.db import MIGRATIONS, Database
from ama.jobs import JobStatus, JobStore
from ama.phase import Phase, phase_of


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
    assert db.execute("SELECT count(*) FROM job_log WHERE job_id = 1").fetchone() == (0,)
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


def test_a_job_ripped_before_the_minimum_title_length_was_a_setting_used_30_seconds(tmp_path):
    before = tmp_path / "before"
    before.mkdir()
    for f in sorted(MIGRATIONS.glob("*.sql")):
        if int(f.name[:4]) <= 19:
            shutil.copy(f, before / f.name)
    db = Database(tmp_path / "s.db", migrations=before)
    db.execute("INSERT INTO jobs (disc_type, status, scratch_dir, started_at, skipped_short) "
               "VALUES ('BD', 'ripped', 'x', '2026-11-04T10:00:00', 4)")
    db.close()

    job = JobStore(Database(tmp_path / "s.db"), tmp_path).get(1)
    assert job is not None and job.min_title_seconds == 30
    assert job.skipped_summary == "Not ripped: 4 Titles shorter than 30 seconds (menus, logos)."


def test_titles_ripped_before_titles_could_be_skipped_are_kept(tmp_path):
    before = tmp_path / "before"
    before.mkdir()
    for f in sorted(MIGRATIONS.glob("*.sql")):
        if int(f.name[:4]) <= 20:
            shutil.copy(f, before / f.name)
    db = Database(tmp_path / "s.db", migrations=before)
    db.execute("INSERT INTO jobs (disc_type, status, scratch_dir, started_at) "
               "VALUES ('BD', 'ripped', 'x', '2026-11-04T10:00:00')")
    db.execute("INSERT INTO titles (job_id, number, makemkv_id, duration_s, size_bytes, audio, "
               "subtitles, segments, file, status, source, name) "
               "VALUES (1, 1, 0, 7293, 1000, 2, 3, '1-2', 't00.mkv', 'ripped', '00800.mpls', 'X')")
    db.close()

    job = JobStore(Database(tmp_path / "s.db"), tmp_path).get(1)
    assert job is not None and [(t.number, t.status, t.source) for t in job.titles] == [
        (1, "ripped", "00800.mpls")]
    assert job.skipped_summary is None


def test_jobs_filed_before_the_phase_was_renamed_are_archived(tmp_path):
    before = tmp_path / "before"
    before.mkdir()
    for f in sorted(MIGRATIONS.glob("*.sql")):
        if int(f.name[:4]) <= 23:
            shutil.copy(f, before / f.name)
    db = Database(tmp_path / "s.db", migrations=before)
    db.execute("INSERT INTO jobs (disc_type, status, scratch_dir, started_at, title, archive_dir, "
               "filed_at, changed_at) VALUES ('BD', 'filed', 'x', '2026-11-04T10:00:00', "
               "'Firefly', 'TV/Firefly', '2026-11-04T12:00:00', '2026-11-04T12:00:00')")
    db.execute("INSERT INTO jobs (disc_type, status, scratch_dir, started_at) "
               "VALUES ('BD', 'review', 'y', '2026-11-04T10:00:00')")
    db.execute("INSERT INTO tv_titles (job_id, title_number, tmdb_id, series, path, encode_status, "
               "queued_at) VALUES (1, 1, 1437, 'Firefly', 'TV/Firefly/e1.mkv', 'filed', "
               "'2026-11-04T11:00:00')")
    db.execute("INSERT INTO extras (job_id, title_number, name, status) VALUES (2, 3, 'Gag', 'filed')")
    db.execute("INSERT INTO job_log (job_id, at, text) VALUES (1, '2026-11-04T10:00:00', "
               "'All kept Titles filed to Firefly; scratch deleted')")
    db.execute("INSERT INTO job_log (job_id, at, text) VALUES (2, '2026-11-04T10:00:00', "
               "'Filed Profiled (2020) to Movies; scratch deleted')")
    db.execute("INSERT INTO runs (kind, job_id, started_at) VALUES ('job', 1, '2026-11-04T10:00:00')")
    db.execute("INSERT INTO steps (run_id, key, position, name, state, started_at) "
               "VALUES (1, 'file', 3, 'File', 'done', '2026-11-04T11:00:00')")
    db.execute("INSERT INTO step_lines (step_id, at, text) VALUES (1, '2026-11-04T11:00:00', "
               "'Couldn''t file to TV (offline); trying again in a while')")
    db.close()

    db = Database(tmp_path / "s.db")
    job = JobStore(db, tmp_path).get(1)
    assert job is not None and job.status == JobStatus.ARCHIVED
    assert phase_of(job.status) == Phase.ARCHIVED
    assert job.archived_at == datetime(2026, 11, 4, 12, 0) and job.title == "Firefly"
    assert db.execute("SELECT encode_status FROM tv_titles").fetchall() == [("archived",)]
    assert db.execute("SELECT status FROM extras").fetchall() == [("archived",)]
    assert db.execute("SELECT key, name FROM steps").fetchall() == [("archive", "Archive")]
    assert [t for _, t in db.execute("SELECT job_id, text FROM job_log ORDER BY job_id")
            .fetchall()] == ["All kept Titles archived to Firefly; scratch deleted",
                             "Archived Profiled (2020) to Movies; scratch deleted"]
    assert db.execute("SELECT text FROM step_lines").fetchall() == [
        ("Couldn't archive to TV (offline); trying again in a while",)]
    db.execute("DELETE FROM jobs WHERE id = 1")  # its children still cascade
    assert db.execute("SELECT count(*) FROM job_log WHERE job_id = 1").fetchone() == (0,)
    assert db.execute("SELECT count(*) FROM tv_titles").fetchone() == (0,)
