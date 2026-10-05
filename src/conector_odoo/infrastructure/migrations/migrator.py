"""Apply ordered, versioned migrations to a SQLite connection.

Applied versions are tracked in ``schema_migrations``. Each migration runs in its own explicit
transaction (the connection must be in autocommit mode, ``isolation_level=None``): a failure rolls
it back and is never recorded. Inconsistent state (a database ahead of the code, or a hole in the
recorded versions) raises instead of guessing.
"""

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from conector_odoo.infrastructure.sqlite import prepare_private_file
from conector_odoo.infrastructure.sync.locks import connection_lock

_TRACKING_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL
)
"""


class MigrationError(RuntimeError):
    """The migration list or the database state is inconsistent, or a migration failed."""


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    statements: tuple[str, ...]


def migrate(conn: sqlite3.Connection, migrations: Sequence[Migration] | None = None) -> list[int]:
    """Apply every pending migration in order and return the versions applied."""
    # Imported lazily: versions.py imports ``Migration`` from this module (circular otherwise).
    from conector_odoo.infrastructure.migrations.versions import MIGRATIONS

    plan = tuple(MIGRATIONS if migrations is None else migrations)
    _check_contiguous(plan)
    conn.execute(_TRACKING_TABLE)
    applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
    known = {m.version for m in plan}
    if unknown := sorted(applied - known):
        raise MigrationError(f"database has unknown migration versions {unknown}")
    if applied != set(range(1, len(applied) + 1)):
        raise MigrationError(f"gap in recorded migration versions {sorted(applied)}")
    done: list[int] = []
    for migration in plan:
        if migration.version not in applied and _apply(conn, migration):
            done.append(migration.version)
    return done


def open_admin_database(path: str) -> sqlite3.Connection:
    """Open (creating it privately if needed) the admin database with FKs on, fully migrated."""
    if path != ":memory:":
        prepare_private_file(Path(path))
    conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        migrate(conn)
    except BaseException:
        conn.close()
        raise
    return conn


def close_admin_database(conn: sqlite3.Connection) -> None:
    """Close the admin connection once the statements running in worker threads have finished.

    Repositories run their blocking SQL in worker threads under the per-connection lock, and a
    cancelled ``await`` does not stop such a thread. Closing the connection under that same lock
    means shutdown waits for it, instead of freeing the connection under a running statement
    (which can crash the interpreter)."""
    with connection_lock(conn):
        conn.close()


def _check_contiguous(plan: Sequence[Migration]) -> None:
    if [m.version for m in plan] != list(range(1, len(plan) + 1)):
        raise MigrationError("migration versions must be contiguous and start at 1")


def _apply(conn: sqlite3.Connection, migration: Migration) -> bool:
    """Apply one migration; return False when a concurrent starter already recorded it."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        # Re-check under the write lock: another process may have applied it since we read.
        if conn.execute(
            "SELECT 1 FROM schema_migrations WHERE version = ?", (migration.version,)
        ).fetchone():
            conn.execute("ROLLBACK")
            return False
        for statement in migration.statements:
            conn.execute(statement)
        conn.execute(
            "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
            (migration.version, migration.name, datetime.now(UTC).isoformat()),
        )
    except sqlite3.Error as exc:
        conn.execute("ROLLBACK")
        raise MigrationError(
            f"migration {migration.version} ({migration.name}) failed: {exc}"
        ) from exc
    conn.execute("COMMIT")
    return True
