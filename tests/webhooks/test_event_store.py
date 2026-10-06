import sqlite3
import stat
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from conector_odoo.infrastructure.webhooks.store import SqliteWebhookEventStore

REDELIVER = 60.0


async def test_claim_is_new_once_then_duplicate() -> None:
    store = SqliteWebhookEventStore(":memory:")
    assert await store.claim("e1", redelivery_after_seconds=REDELIVER) == "new"
    assert await store.claim("e1", redelivery_after_seconds=REDELIVER) == "duplicate"
    assert await store.claim("e2", redelivery_after_seconds=REDELIVER) == "new"
    assert await store.status("e1") == "received"
    await store.close()


async def test_processed_events_are_duplicates_even_when_old() -> None:
    store = SqliteWebhookEventStore(":memory:")
    await store.claim("e1", redelivery_after_seconds=REDELIVER)
    await store.mark_processed("e1")
    assert await store.status("e1") == "processed"
    later = datetime.now(UTC) + timedelta(hours=1)
    assert await store.claim("e1", redelivery_after_seconds=REDELIVER, now=later) == "duplicate"
    await store.close()


async def test_received_events_are_in_flight_until_the_redelivery_window_passes() -> None:
    store = SqliteWebhookEventStore(":memory:")
    start = datetime(2026, 1, 1, tzinfo=UTC)
    assert await store.claim("e1", redelivery_after_seconds=REDELIVER, now=start) == "new"
    soon = start + timedelta(seconds=59)
    assert await store.claim("e1", redelivery_after_seconds=REDELIVER, now=soon) == "duplicate"
    stale = start + timedelta(seconds=60)
    assert await store.claim("e1", redelivery_after_seconds=REDELIVER, now=stale) == "redeliver"
    # the redelivery refreshed received_at: the next attempt is in flight again
    after = stale + timedelta(seconds=10)
    assert await store.claim("e1", redelivery_after_seconds=REDELIVER, now=after) == "duplicate"
    await store.close()


async def test_claim_uses_the_injectable_clock() -> None:
    store = SqliteWebhookEventStore(":memory:")
    now = datetime(2026, 1, 1, tzinfo=UTC)
    store.clock = lambda: now
    await store.claim("e1", redelivery_after_seconds=REDELIVER)
    store.clock = lambda: now + timedelta(seconds=61)
    assert await store.claim("e1", redelivery_after_seconds=REDELIVER) == "redeliver"
    await store.close()


async def test_unparsable_received_at_is_treated_as_stale() -> None:
    store = SqliteWebhookEventStore(":memory:")
    await store.claim("e1", redelivery_after_seconds=REDELIVER)
    store._conn.execute("UPDATE webhook_events SET received_at = 'garbage'")
    assert await store.claim("e1", redelivery_after_seconds=REDELIVER) == "redeliver"
    await store.close()


async def test_purge_removes_only_old_events() -> None:
    store = SqliteWebhookEventStore(":memory:")
    await store.claim("old", redelivery_after_seconds=REDELIVER)
    later = datetime.now(UTC) + timedelta(hours=25)
    assert await store.purge_older_than(24, now=later) == 1
    assert await store.claim("old", redelivery_after_seconds=REDELIVER) == "new"
    assert await store.purge_older_than(24) == 0
    await store.close()


async def test_events_survive_reopening_and_share_the_database_file(tmp_path: Path) -> None:
    path = str(tmp_path / "shared.sqlite3")
    first = SqliteWebhookEventStore(path)
    await first.claim("e1", redelivery_after_seconds=REDELIVER)
    await first.close()
    second = SqliteWebhookEventStore(path)
    assert await second.claim("e1", redelivery_after_seconds=REDELIVER) == "duplicate"
    await second.close()


async def test_a_table_without_status_column_is_migrated_as_processed(tmp_path: Path) -> None:
    path = tmp_path / "old.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE webhook_events (event_id TEXT PRIMARY KEY, received_at TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO webhook_events VALUES ('legacy', ?)", (datetime.now(UTC).isoformat(),)
    )
    conn.commit()
    conn.close()
    store = SqliteWebhookEventStore(str(path))
    assert await store.status("legacy") == "processed"
    assert await store.claim("legacy", redelivery_after_seconds=0) == "duplicate"
    await store.close()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
async def test_database_file_is_private(tmp_path: Path) -> None:
    path = tmp_path / "d" / "w.sqlite3"
    await SqliteWebhookEventStore(str(path)).close()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
