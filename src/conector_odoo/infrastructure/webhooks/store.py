"""SQLite store of received webhook ``event_id`` values, used to drop Odoo's retried deliveries.

It opens its own connection to the same database file as the idempotency store (SQLite handles
several connections) and creates its own table, so the two concerns stay independent. Rows are
removed by ``purge_older_than`` (run by the app lifespan together with the idempotency purge).
"""

import asyncio
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

from conector_odoo.infrastructure.idempotency.sqlite_store import prepare_private_file

_SCHEMA = """
CREATE TABLE IF NOT EXISTS webhook_events (
    event_id TEXT PRIMARY KEY,
    received_at TEXT NOT NULL
)
"""


class SqliteWebhookEventStore:
    def __init__(self, path: str) -> None:
        if path != ":memory:":
            prepare_private_file(Path(path))
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.execute(_SCHEMA)

    async def register(self, event_id: str) -> bool:
        """Record ``event_id``; ``True`` if it is new, ``False`` if it was already seen."""
        return await asyncio.to_thread(self._register, event_id)

    async def purge_older_than(self, hours: float, *, now: datetime | None = None) -> int:
        cutoff = ((now or datetime.now(UTC)) - timedelta(hours=hours)).isoformat()
        return await asyncio.to_thread(
            self._execute, "DELETE FROM webhook_events WHERE received_at < ?", (cutoff,)
        )

    async def close(self) -> None:
        await asyncio.to_thread(self._close)

    def _register(self, event_id: str) -> bool:
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO webhook_events (event_id, received_at) VALUES (?, ?)",
                    (event_id, datetime.now(UTC).isoformat()),
                )
            except sqlite3.IntegrityError:
                return False
            return True

    def _execute(self, sql: str, params: tuple[str, ...]) -> int:
        with self._lock:
            return self._conn.execute(sql, params).rowcount

    def _close(self) -> None:
        with self._lock:
            self._conn.close()
