import stat
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from conector_odoo.infrastructure.webhooks.store import SqliteWebhookEventStore


async def test_register_returns_true_once_per_event_id() -> None:
    store = SqliteWebhookEventStore(":memory:")
    assert await store.register("e1") is True
    assert await store.register("e1") is False
    assert await store.register("e2") is True
    await store.close()


async def test_purge_removes_only_old_events() -> None:
    store = SqliteWebhookEventStore(":memory:")
    await store.register("old")
    later = datetime.now(UTC) + timedelta(hours=25)
    assert await store.purge_older_than(24, now=later) == 1
    assert await store.register("old") is True
    assert await store.purge_older_than(24) == 0
    await store.close()


async def test_events_survive_reopening_and_share_the_database_file(tmp_path: Path) -> None:
    path = str(tmp_path / "shared.sqlite3")
    first = SqliteWebhookEventStore(path)
    await first.register("e1")
    await first.close()
    second = SqliteWebhookEventStore(path)
    assert await second.register("e1") is False
    await second.close()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
async def test_database_file_is_private(tmp_path: Path) -> None:
    path = tmp_path / "d" / "w.sqlite3"
    await SqliteWebhookEventStore(str(path)).close()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
