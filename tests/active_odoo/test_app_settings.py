"""Migration 7 and the SQLite key/value store behind the active Odoo connection."""

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from conector_odoo.application.active_odoo import OdooActivationLog
from conector_odoo.infrastructure.app_settings import SqliteAppSettings
from conector_odoo.infrastructure.migrations import MIGRATIONS, open_admin_database


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = open_admin_database(":memory:")
    yield connection
    connection.close()


def test_migration_seven_creates_app_settings(conn: sqlite3.Connection) -> None:
    assert MIGRATIONS[-1].version >= 7
    columns = [row[1] for row in conn.execute("PRAGMA table_info(app_settings)")]
    assert columns == ["key", "value", "updated_at"]


async def test_set_get_delete_round_trip(conn: sqlite3.Connection) -> None:
    store = SqliteAppSettings(conn)
    assert await store.get_all("odoo.") == {}
    await store.set_many({"odoo.a": "1", "odoo.b": "2", "other.c": "3"})
    assert await store.get_all("odoo.") == {"odoo.a": "1", "odoo.b": "2"}
    await store.set_many({"odoo.a": "9"})
    assert (await store.get_all("odoo."))["odoo.a"] == "9"
    await store.delete("odoo.a")
    assert "odoo.a" not in await store.get_all("odoo.")


async def test_the_prefix_is_not_a_like_pattern(conn: sqlite3.Connection) -> None:
    store = SqliteAppSettings(conn)
    await store.set_many({"odoo_x": "1", "odoo.y": "2"})
    assert await store.get_all("odoo.") == {"odoo.y": "2"}


async def test_activation_log_round_trip_and_forget(conn: sqlite3.Connection) -> None:
    at = datetime(2026, 1, 2, 3, 4, tzinfo=UTC)
    log = OdooActivationLog(SqliteAppSettings(conn), clock=lambda: at)
    empty = await log.load()
    assert empty.active_profile_id is None and empty.per_profile == {}
    await log.record_activation(7)
    record = await log.load()
    assert (record.active_profile_id, record.last_connected_profile_id) == (7, 7)
    assert record.last_connected_at == at
    assert record.per_profile == {7: at}
    await log.clear_active()
    assert (await log.load()).active_profile_id is None
    await log.forget_profile(7)
    assert (await log.load()).per_profile == {}


async def test_a_corrupt_stored_value_is_ignored(conn: sqlite3.Connection) -> None:
    store = SqliteAppSettings(conn)
    await store.set_many({"odoo.active_profile_id": "not-a-number", "odoo.last_connected_at": "x"})
    record = await OdooActivationLog(store).load()
    assert record.active_profile_id is None
    assert record.last_connected_at is None
