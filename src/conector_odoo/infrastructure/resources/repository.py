"""SQLite ``ResourceCatalogRepository`` over the ``resources`` table.

The configuration is stored as versioned JSON in ``config_json`` (see ``resource_codec``);
``source`` and ``updated_at`` come from migration 3. Deleting a connection profile that still has
catalog entries is refused by the foreign key (``ProfileInUse``), exactly as for jobs.
"""

import asyncio
import logging
import sqlite3
import threading
from datetime import UTC, datetime
from typing import Any

from conector_odoo.domain.errors import (
    CatalogResourceNotFound,
    ProfileNotFound,
    ResourceConfigInvalid,
)
from conector_odoo.domain.resource_codec import resource_config_from_json, resource_config_to_json
from conector_odoo.domain.resources import (
    CatalogListing,
    ResourceConfig,
    ResourceProblem,
    ResourceSource,
    StoredResource,
)

logger = logging.getLogger(__name__)

StoredResources = list[StoredResource]  # the ``list`` method below shadows the builtin

_COLUMNS = "profile_id, config_json, source, updated_at, created_at"


class SqliteResourceCatalogRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = threading.Lock()

    async def save(
        self, profile_id: int, config: ResourceConfig, source: ResourceSource
    ) -> StoredResource:
        return await asyncio.to_thread(self._save, profile_id, config, source)

    async def get(self, profile_id: int, name: str) -> StoredResource | None:
        return await asyncio.to_thread(self._get, profile_id, name)

    async def list(self, profile_id: int) -> StoredResources:
        return (await self.list_with_problems(profile_id)).items

    async def list_with_problems(self, profile_id: int) -> CatalogListing:
        return await asyncio.to_thread(self._list, profile_id)

    async def delete(self, profile_id: int, name: str) -> None:
        await asyncio.to_thread(self._delete, profile_id, name)

    def _save(
        self, profile_id: int, config: ResourceConfig, source: ResourceSource
    ) -> StoredResource:
        now = datetime.now(UTC).isoformat()
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO resources (profile_id, name, config_json, source, created_at, "
                    "updated_at) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (profile_id, name) DO "
                    "UPDATE SET config_json = excluded.config_json, source = excluded.source, "
                    "updated_at = excluded.updated_at",
                    (
                        profile_id,
                        config.name,
                        resource_config_to_json(config),
                        source.value,
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError:
                raise ProfileNotFound(f"connection profile {profile_id} not found") from None
            row = self._select(profile_id, config.name)
        assert row is not None
        return _to_stored(row)

    def _get(self, profile_id: int, name: str) -> StoredResource | None:
        with self._lock:
            row = self._select(profile_id, name)
        return None if row is None else _to_stored(row)

    def _list(self, profile_id: int) -> CatalogListing:
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {_COLUMNS}, name FROM resources WHERE profile_id = ? ORDER BY name",
                (profile_id,),
            ).fetchall()
        items: StoredResources = []
        problems: list[ResourceProblem] = []
        for row in rows:
            try:
                items.append(_to_stored(row))
            except (ResourceConfigInvalid, ValueError, TypeError) as exc:
                # One corrupt row must not hide the rest of the catalog.
                logger.warning(
                    "skipping a corrupt catalog entry",
                    extra={"profile_id": profile_id, "resource": row[5]},
                )
                problems.append(ResourceProblem(row[5], str(exc)))
        return CatalogListing(items, problems)

    def _delete(self, profile_id: int, name: str) -> None:
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM resources WHERE profile_id = ? AND name = ?", (profile_id, name)
            )
        if cursor.rowcount == 0:
            raise CatalogResourceNotFound(f"resource {name!r} not found in profile {profile_id}")

    def _select(self, profile_id: int, name: str) -> tuple[Any, ...] | None:
        row: tuple[Any, ...] | None = self._conn.execute(
            f"SELECT {_COLUMNS} FROM resources WHERE profile_id = ? AND name = ?",
            (profile_id, name),
        ).fetchone()
        return row


def _to_stored(row: tuple[Any, ...]) -> StoredResource:
    config = resource_config_from_json(row[1])  # first: a corrupt entry must say so clearly
    return StoredResource(
        profile_id=row[0],
        config=config,
        source=ResourceSource(row[2]),
        updated_at=datetime.fromisoformat(row[3] or row[4]),
    )
