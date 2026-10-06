"""SQLite ``MappingRepository`` over the ``mappings`` table.

Each row is one immutable version (unique by name and version) holding the definition as
versioned JSON (see ``mapping_codec``). A mapping that a sync job references through
``sync_jobs.mapping_id`` (any of its versions) cannot be deleted.
"""

import asyncio
import sqlite3
import threading
from datetime import UTC, datetime
from typing import Any

from conector_odoo.domain.errors import MappingInUse, MappingNotFound
from conector_odoo.domain.mapping import MappingDefinition, StoredMapping
from conector_odoo.domain.mapping_codec import mapping_from_json, mapping_to_json

StoredMappings = list[StoredMapping]  # the ports use ``list`` too; keep annotations unambiguous

_COLUMNS = "name, version, definition_json, created_at"


class SqliteMappingRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = threading.Lock()

    async def save_new_version(self, definition: MappingDefinition) -> StoredMapping:
        return await asyncio.to_thread(self._save, definition)

    async def get(self, name: str, version: int | None = None) -> StoredMapping | None:
        return await asyncio.to_thread(self._get, name, version)

    async def list_latest(self) -> StoredMappings:
        return await asyncio.to_thread(self._list_latest)

    async def list_versions(self, name: str) -> StoredMappings:
        return await asyncio.to_thread(self._list_versions, name)

    async def delete(self, name: str) -> None:
        await asyncio.to_thread(self._delete, name)

    def _save(self, definition: MappingDefinition) -> StoredMapping:
        document = mapping_to_json(definition)  # first: unserialisable definitions fail early
        with self._lock:
            latest = self._select(definition.name, None)
            if latest is not None and mapping_from_json(latest[2]) == definition:
                return _to_stored(latest)
            version = (latest[1] + 1) if latest is not None else 1
            self._conn.execute(
                "INSERT INTO mappings (name, version, definition_json, created_at) "
                "VALUES (?, ?, ?, ?)",
                (definition.name, version, document, datetime.now(UTC).isoformat()),
            )
            row = self._select(definition.name, version)
        assert row is not None
        return _to_stored(row)

    def _get(self, name: str, version: int | None) -> StoredMapping | None:
        with self._lock:
            row = self._select(name, version)
        return None if row is None else _to_stored(row)

    def _list_latest(self) -> StoredMappings:
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {_COLUMNS} FROM mappings m WHERE version = "
                "(SELECT MAX(version) FROM mappings WHERE name = m.name) ORDER BY name"
            ).fetchall()
        return [_to_stored(row) for row in rows]

    def _list_versions(self, name: str) -> StoredMappings:
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {_COLUMNS} FROM mappings WHERE name = ? ORDER BY version", (name,)
            ).fetchall()
        return [_to_stored(row) for row in rows]

    def _delete(self, name: str) -> None:
        with self._lock:
            referenced = self._conn.execute(
                "SELECT 1 FROM sync_jobs WHERE mapping_id IN "
                "(SELECT id FROM mappings WHERE name = ?) LIMIT 1",
                (name,),
            ).fetchone()
            if referenced is not None:
                raise MappingInUse(f"mapping {name!r} is used by a sync job")
            cursor = self._conn.execute("DELETE FROM mappings WHERE name = ?", (name,))
        if cursor.rowcount == 0:
            raise MappingNotFound(f"mapping {name!r} not found")

    def _select(self, name: str, version: int | None) -> tuple[Any, ...] | None:
        if version is None:
            query = f"SELECT {_COLUMNS} FROM mappings WHERE name = ? ORDER BY version DESC LIMIT 1"
            params: tuple[Any, ...] = (name,)
        else:
            query = f"SELECT {_COLUMNS} FROM mappings WHERE name = ? AND version = ?"
            params = (name, version)
        row: tuple[Any, ...] | None = self._conn.execute(query, params).fetchone()
        return row


def _to_stored(row: tuple[Any, ...]) -> StoredMapping:
    return StoredMapping(
        name=row[0],
        version=row[1],
        definition=mapping_from_json(row[2]),
        created_at=datetime.fromisoformat(row[3]),
    )
