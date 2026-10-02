from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from conector_odoo.infrastructure.idempotency.sqlite_store import SqliteIdempotencyStore

SCOPE = "POST /customers"


@pytest.fixture
def store(tmp_path: Path) -> SqliteIdempotencyStore:
    return SqliteIdempotencyStore(str(tmp_path / "idem.sqlite3"))


async def test_first_begin_inserts_an_in_progress_record_and_returns_none(
    store: SqliteIdempotencyStore,
) -> None:
    assert await store.begin("k1", SCOPE, "hash-a") is None
    record = await store.get("k1", SCOPE)
    assert record is not None
    assert (record.status, record.request_hash) == ("in_progress", "hash-a")
    assert record.response_status is None


async def test_second_begin_returns_the_existing_record(store: SqliteIdempotencyStore) -> None:
    await store.begin("k1", SCOPE, "hash-a")
    existing = await store.begin("k1", SCOPE, "hash-b")
    assert existing is not None
    assert (existing.status, existing.request_hash) == ("in_progress", "hash-a")


async def test_complete_stores_the_response_for_replay(store: SqliteIdempotencyStore) -> None:
    await store.begin("k1", SCOPE, "hash-a")
    await store.complete("k1", SCOPE, 201, '{"id": 1}', {"Location": "/customers/1"})
    record = await store.begin("k1", SCOPE, "hash-a")
    assert record is not None
    assert record.status == "completed"
    assert record.response_status == 201
    assert record.response_body == '{"id": 1}'
    assert record.response_headers == {"Location": "/customers/1"}


async def test_release_deletes_the_record_so_the_key_can_be_reused(
    store: SqliteIdempotencyStore,
) -> None:
    await store.begin("k1", SCOPE, "hash-a")
    await store.release("k1", SCOPE)
    assert await store.get("k1", SCOPE) is None
    assert await store.begin("k1", SCOPE, "hash-b") is None


async def test_same_key_in_another_scope_is_independent(store: SqliteIdempotencyStore) -> None:
    await store.begin("k1", SCOPE, "hash-a")
    assert await store.begin("k1", "POST /sale-orders", "hash-a") is None


async def test_purge_older_than_removes_only_old_records(store: SqliteIdempotencyStore) -> None:
    await store.begin("old", SCOPE, "h")
    later = datetime.now(UTC) + timedelta(hours=25)
    assert await store.purge_older_than(24, now=later) == 1
    assert await store.get("old", SCOPE) is None
    await store.begin("fresh", SCOPE, "h")
    assert await store.purge_older_than(24) == 0
    assert await store.get("fresh", SCOPE) is not None


async def test_records_survive_reopening_the_database(tmp_path: Path) -> None:
    path = str(tmp_path / "nested" / "dir" / "idem.sqlite3")
    first = SqliteIdempotencyStore(path)
    await first.begin("k1", SCOPE, "hash-a")
    await first.complete("k1", SCOPE, 201, "{}", {})
    await first.close()
    second = SqliteIdempotencyStore(path)
    record = await second.get("k1", SCOPE)
    await second.close()
    assert record is not None
    assert record.status == "completed"


async def test_in_memory_database_is_supported() -> None:
    store = SqliteIdempotencyStore(":memory:")
    assert await store.begin("k", SCOPE, "h") is None
    await store.close()
