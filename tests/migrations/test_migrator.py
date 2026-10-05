import sqlite3
from pathlib import Path

import pytest

from conector_odoo.infrastructure.migrations import (
    MIGRATIONS,
    Migration,
    MigrationError,
    migrate,
    open_admin_database,
)

EXPECTED_TABLES = {
    "schema_migrations",
    "connection_profiles",
    "resources",
    "mappings",
    "sync_jobs",
    "sync_runs",
    "run_errors",
    "xref",
    "admin_users",
}


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {row[0] for row in rows}


def test_fresh_database_gets_every_table_and_records_versions() -> None:
    conn = connect()
    applied = migrate(conn)
    assert tables(conn) >= EXPECTED_TABLES
    assert applied == [m.version for m in MIGRATIONS]
    rows = conn.execute("SELECT version, name, applied_at FROM schema_migrations").fetchall()
    assert [r[0] for r in rows] == applied
    assert all(r[1] and r[2] for r in rows)


def test_second_run_applies_nothing() -> None:
    conn = connect()
    migrate(conn)
    assert migrate(conn) == []
    count = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
    assert count == len(MIGRATIONS)


def test_failed_migration_rolls_back_and_is_not_recorded() -> None:
    conn = connect()
    bad = Migration(
        2, "bad", ("CREATE TABLE half_done (a INTEGER)", "INSERT INTO missing_table VALUES (1)")
    )
    migrate(conn)
    with pytest.raises(MigrationError, match="bad"):
        migrate(conn, (*MIGRATIONS, bad))
    assert "half_done" not in tables(conn)
    versions = [r[0] for r in conn.execute("SELECT version FROM schema_migrations")]
    assert 2 not in versions


def test_gapped_migration_list_fails_loudly() -> None:
    conn = connect()
    with pytest.raises(MigrationError, match="contiguous"):
        migrate(conn, (Migration(1, "a", ()), Migration(3, "c", ())))


def test_database_ahead_of_code_fails_loudly() -> None:
    conn = connect()
    migrate(conn)
    conn.execute("INSERT INTO schema_migrations VALUES (99, 'future', 'now')")
    with pytest.raises(MigrationError, match="unknown"):
        migrate(conn)


def test_recorded_gap_fails_loudly() -> None:
    conn = connect()
    migrations = (Migration(1, "a", ()), Migration(2, "b", ()))
    migrate(conn, migrations)
    conn.execute("DELETE FROM schema_migrations WHERE version = 1")
    with pytest.raises(MigrationError, match="gap"):
        migrate(conn, migrations)


def test_open_admin_database_migrates_and_enforces_foreign_keys(tmp_path: Path) -> None:
    conn = open_admin_database(str(tmp_path / "sub" / "admin.db"))
    try:
        assert tables(conn) >= EXPECTED_TABLES
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        conn.close()


def test_open_admin_database_supports_memory() -> None:
    conn = open_admin_database(":memory:")
    conn.close()
