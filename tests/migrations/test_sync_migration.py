import sqlite3

from conector_odoo.infrastructure.migrations import migrate
from conector_odoo.infrastructure.migrations.versions import MIGRATIONS

NOW = "2026-01-01T00:00:00+00:00"


def columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def test_migration_four_upgrades_a_database_already_at_version_three() -> None:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.execute("PRAGMA foreign_keys = ON")
    assert migrate(conn, MIGRATIONS[:3]) == [1, 2, 3]
    conn.execute(
        "INSERT INTO connection_profiles (id, name, type, base_url, auth_method, created_at, "
        "updated_at) VALUES (1, 'p', 'rest', 'https://x', 'none', ?, ?)",
        (NOW, NOW),
    )
    conn.execute(
        "INSERT INTO mappings (id, name, version, definition_json, created_at) "
        "VALUES (1, 'm', 1, '{}', ?)",
        (NOW,),
    )
    conn.execute(
        "INSERT INTO sync_jobs (id, name, source_profile_id, target_profile_id, mapping_id, "
        "direction, upsert_key, created_at, updated_at) VALUES (1, 'old', 1, 1, 1, 'push', 'id', "
        "?, ?)",
        (NOW, NOW),
    )
    conn.execute(
        "INSERT INTO sync_runs (id, job_id, status, trigger, started_at) "
        "VALUES (1, 1, 'succeeded', 'manual', ?)",
        (NOW,),
    )
    conn.execute("INSERT INTO run_errors (run_id, message) VALUES (1, 'old error')")
    conn.execute(
        "INSERT INTO xref (job_id, resource, source_id, target_id, updated_at) "
        "VALUES (1, 'c', 's', 't', ?)",
        (NOW,),
    )

    assert migrate(conn) == [4]

    assert {"source_resource", "mapping_name", "reverse_mapping_id"} <= columns(conn, "sync_jobs")
    assert {"conflicts", "checkpoint_json", "parent_run_id"} <= columns(conn, "sync_runs")
    assert {"side", "kind", "retryable"} <= columns(conn, "run_errors")
    assert {"content_hash", "reverse_hash"} <= columns(conn, "xref")
    # existing rows survive with sane defaults
    assert conn.execute(
        "SELECT name, source_resource, mapping_version FROM sync_jobs"
    ).fetchone() == (
        "old",
        "",
        None,
    )
    assert conn.execute("SELECT conflicts, checkpoint_json FROM sync_runs").fetchone() == (0, "{}")
    assert conn.execute("SELECT side, kind, retryable FROM run_errors").fetchone() == (
        "source",
        "other",
        1,
    )
    assert conn.execute("SELECT content_hash FROM xref").fetchone() == (None,)
    assert migrate(conn) == []  # idempotent
