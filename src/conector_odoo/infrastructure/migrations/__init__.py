"""Versioned SQLite migrations for the admin database."""

from conector_odoo.infrastructure.migrations.migrator import (
    Migration,
    MigrationError,
    close_admin_database,
    migrate,
    open_admin_database,
)
from conector_odoo.infrastructure.migrations.versions import MIGRATIONS

__all__ = [
    "MIGRATIONS",
    "Migration",
    "MigrationError",
    "close_admin_database",
    "migrate",
    "open_admin_database",
]
