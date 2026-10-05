"""Versioned SQLite migrations for the admin database."""

from conector_odoo.infrastructure.migrations.migrator import (
    Migration,
    MigrationError,
    migrate,
    open_admin_database,
)
from conector_odoo.infrastructure.migrations.versions import MIGRATIONS

__all__ = ["MIGRATIONS", "Migration", "MigrationError", "migrate", "open_admin_database"]
