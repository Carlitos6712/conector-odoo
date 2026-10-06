"""SQLite ``AppSettingsRepository`` over the ``app_settings`` table (shared admin connection)."""

import asyncio
import sqlite3
from datetime import UTC, datetime

from conector_odoo.infrastructure.sync.locks import connection_lock


class SqliteAppSettings:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = connection_lock(conn)

    async def get_all(self, prefix: str) -> dict[str, str]:
        return await asyncio.to_thread(self._get_all, prefix)

    async def set_many(self, values: dict[str, str]) -> None:
        await asyncio.to_thread(self._set_many, values)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._delete, key)

    def _get_all(self, prefix: str) -> dict[str, str]:
        with self._lock:
            # substr, not LIKE: the prefix is literal and may contain ``_`` or ``%``.
            rows = self._conn.execute(
                "SELECT key, value FROM app_settings WHERE substr(key, 1, ?) = ?",
                (len(prefix), prefix),
            ).fetchall()
        return {key: value for key, value in rows}

    def _set_many(self, values: dict[str, str]) -> None:
        now = datetime.now(UTC).isoformat()
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                for key, value in values.items():
                    self._conn.execute(
                        "INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
                        "updated_at = excluded.updated_at",
                        (key, value, now),
                    )
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    def _delete(self, key: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM app_settings WHERE key = ?", (key,))
