import logging
import stat
import sys
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


async def test_mark_unknown_keeps_the_error_response_and_blocks_the_key(
    store: SqliteIdempotencyStore,
) -> None:
    await store.begin("k1", SCOPE, "hash-a")
    await store.mark_unknown("k1", SCOPE, 502, '{"error":"odoo_unavailable"}', {})
    record = await store.begin("k1", SCOPE, "hash-a")
    assert record is not None
    assert record.status == "unknown"
    assert record.response_status == 502
    assert record.response_body == '{"error":"odoo_unavailable"}'


async def test_stale_in_progress_rows_become_unknown_on_begin(
    store: SqliteIdempotencyStore,
) -> None:
    await store.begin("k1", SCOPE, "hash-a")
    later = datetime.now(UTC) + timedelta(seconds=301)
    record = await store.begin("k1", SCOPE, "hash-a", now=later)
    assert record is not None
    assert record.status == "unknown"
    persisted = await store.get("k1", SCOPE)
    assert persisted is not None
    assert persisted.status == "unknown"


async def test_fresh_in_progress_rows_stay_in_progress(store: SqliteIdempotencyStore) -> None:
    await store.begin("k1", SCOPE, "hash-a")
    soon = datetime.now(UTC) + timedelta(seconds=10)
    record = await store.begin("k1", SCOPE, "hash-a", now=soon)
    assert record is not None
    assert record.status == "in_progress"


async def test_the_in_progress_timeout_is_configurable(tmp_path: Path) -> None:
    store = SqliteIdempotencyStore(str(tmp_path / "i.sqlite3"), in_progress_timeout_seconds=5)
    await store.begin("k1", SCOPE, "hash-a")
    record = await store.begin("k1", SCOPE, "hash-a", now=datetime.now(UTC) + timedelta(seconds=6))
    assert record is not None
    assert record.status == "unknown"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
async def test_database_file_and_new_parent_directory_are_private(tmp_path: Path) -> None:
    path = tmp_path / "fresh" / "idem.sqlite3"
    store = SqliteIdempotencyStore(str(path))
    await store.begin("k1", SCOPE, "hash-a")
    await store.close()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
async def test_existing_database_file_is_tightened_to_0600(tmp_path: Path) -> None:
    path = tmp_path / "idem.sqlite3"
    path.touch(mode=0o644)
    path.chmod(0o644)
    await SqliteIdempotencyStore(str(path)).close()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


async def test_naive_created_at_is_read_as_utc(store: SqliteIdempotencyStore) -> None:
    await store.begin("k1", SCOPE, "hash-a")
    naive_old = (datetime.now(UTC) - timedelta(seconds=600)).replace(tzinfo=None).isoformat()
    store._conn.execute("UPDATE idempotency_keys SET created_at = ?", (naive_old,))
    record = await store.begin("k1", SCOPE, "hash-a")
    assert record is not None
    assert record.status == "unknown"


async def test_fresh_naive_created_at_stays_in_progress(store: SqliteIdempotencyStore) -> None:
    await store.begin("k1", SCOPE, "hash-a")
    naive_now = datetime.now(UTC).replace(tzinfo=None).isoformat()
    store._conn.execute("UPDATE idempotency_keys SET created_at = ?", (naive_now,))
    record = await store.begin("k1", SCOPE, "hash-a")
    assert record is not None
    assert record.status == "in_progress"


async def test_unparsable_created_at_is_abandoned_and_logged(
    store: SqliteIdempotencyStore, caplog: pytest.LogCaptureFixture
) -> None:
    await store.begin("k1", SCOPE, "hash-a")
    store._conn.execute("UPDATE idempotency_keys SET created_at = 'not-a-date'")
    with caplog.at_level(logging.WARNING):
        record = await store.begin("k1", SCOPE, "hash-a")
    assert record is not None
    assert record.status == "unknown"
    assert any("unparsable created_at" in r.getMessage() for r in caplog.records)


async def test_the_injectable_clock_drives_begin() -> None:
    store = SqliteIdempotencyStore(":memory:", in_progress_timeout_seconds=5)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    store.clock = lambda: start
    await store.begin("k1", SCOPE, "hash-a")
    store.clock = lambda: start + timedelta(seconds=6)
    record = await store.begin("k1", SCOPE, "hash-a")
    assert record is not None
    assert record.status == "unknown"
