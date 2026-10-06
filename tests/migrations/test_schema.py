import sqlite3

import pytest

from conector_odoo.infrastructure.migrations import migrate

NOW = "2026-01-01T00:00:00Z"


@pytest.fixture
def conn() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.execute("PRAGMA foreign_keys = ON")
    migrate(connection)
    return connection


def add_profile(conn: sqlite3.Connection, name: str = "odoo") -> int:
    cur = conn.execute(
        "INSERT INTO connection_profiles (name, type, base_url, auth_method, created_at,"
        " updated_at) VALUES (?, 'rest', 'https://x', 'bearer', ?, ?)",
        (name, NOW, NOW),
    )
    assert cur.lastrowid is not None
    return cur.lastrowid


def add_mapping(conn: sqlite3.Connection, name: str = "m", version: int = 1) -> int:
    cur = conn.execute(
        "INSERT INTO mappings (name, version, definition_json, created_at) VALUES (?, ?, '{}', ?)",
        (name, version, NOW),
    )
    assert cur.lastrowid is not None
    return cur.lastrowid


def add_job(conn: sqlite3.Connection) -> int:
    source, target = add_profile(conn, "src"), add_profile(conn, "dst")
    cur = conn.execute(
        "INSERT INTO sync_jobs (name, source_profile_id, target_profile_id, mapping_id,"
        " direction, upsert_key, created_at, updated_at) VALUES ('j', ?, ?, ?, 'push', 'id', ?, ?)",
        (source, target, add_mapping(conn), NOW, NOW),
    )
    assert cur.lastrowid is not None
    return cur.lastrowid


def test_admin_user_role_must_be_admin_or_operator(conn: sqlite3.Connection) -> None:
    sql = (
        "INSERT INTO admin_users (username, password_hash, role, created_at) VALUES (?, 'h', ?, ?)"
    )
    conn.execute(sql, ("a", "admin", NOW))
    conn.execute(sql, ("b", "operator", NOW))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql, ("c", "root", NOW))


def test_admin_username_is_unique(conn: sqlite3.Connection) -> None:
    sql = (
        "INSERT INTO admin_users (username, password_hash, role, created_at) VALUES (?, 'h', ?, ?)"
    )
    conn.execute(sql, ("a", "admin", NOW))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql, ("a", "operator", NOW))


def test_profile_name_is_unique(conn: sqlite3.Connection) -> None:
    add_profile(conn, "dup")
    with pytest.raises(sqlite3.IntegrityError):
        add_profile(conn, "dup")


def test_resource_requires_existing_profile(conn: sqlite3.Connection) -> None:
    sql = "INSERT INTO resources (profile_id, name, created_at) VALUES (?, 'r', ?)"
    conn.execute(sql, (add_profile(conn), NOW))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql, (9999, NOW))


def test_profile_in_use_by_resource_cannot_be_deleted(conn: sqlite3.Connection) -> None:
    profile = add_profile(conn)
    conn.execute(
        "INSERT INTO resources (profile_id, name, created_at) VALUES (?, 'r', ?)", (profile, NOW)
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM connection_profiles WHERE id = ?", (profile,))


def test_mapping_name_version_is_unique(conn: sqlite3.Connection) -> None:
    add_mapping(conn, "m", 1)
    add_mapping(conn, "m", 2)
    with pytest.raises(sqlite3.IntegrityError):
        add_mapping(conn, "m", 1)


def test_job_requires_existing_mapping_and_profiles(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO sync_jobs (name, source_profile_id, target_profile_id, mapping_id,"
            " direction, upsert_key, created_at, updated_at) VALUES ('j', 1, 2, 3, 'push', 'id',"
            " ?, ?)",
            (NOW, NOW),
        )


def test_run_requires_job_and_errors_cascade_with_run(conn: sqlite3.Connection) -> None:
    sql = (
        "INSERT INTO sync_runs (job_id, status, trigger, started_at)"
        " VALUES (?, 'running', 'manual', ?)"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql, (404, NOW))
    run = conn.execute(sql, (add_job(conn), NOW)).lastrowid
    conn.execute(
        "INSERT INTO run_errors (run_id, record_ref, message) VALUES (?, 'r1', 'boom')", (run,)
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO run_errors (run_id, message) VALUES (404, 'x')")
    conn.execute("DELETE FROM sync_runs WHERE id = ?", (run,))
    assert conn.execute("SELECT COUNT(*) FROM run_errors").fetchone()[0] == 0


def test_xref_is_unique_per_job_resource_and_source_id(conn: sqlite3.Connection) -> None:
    job = add_job(conn)
    sql = (
        "INSERT INTO xref (job_id, resource, source_id, target_id, updated_at)"
        " VALUES (?, ?, ?, ?, ?)"
    )
    conn.execute(sql, (job, "partner", "s1", "t1", NOW))
    conn.execute(sql, (job, "partner", "s2", "t2", NOW))
    conn.execute(sql, (job, "product", "s1", "t3", NOW))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql, (job, "partner", "s1", "t9", NOW))


def test_boolean_columns_reject_non_boolean_values(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO connection_profiles (name, type, base_url, auth_method, tls_verify,"
            " created_at, updated_at) VALUES ('p', 'rest', 'u', 'none', 5, ?, ?)",
            (NOW, NOW),
        )
