"""SQLite store of received webhook events: two-phase dedup that gives at-least-once delivery.

Each ``event_id`` row moves ``received`` -> ``processed``:

* ``claim`` inserts ``received`` *before* the event is dispatched.
* the background task calls ``mark_processed`` only after every handler succeeded.
* A redelivery of a ``processed`` id is a duplicate (acknowledged, not dispatched). A ``received``
  id newer than ``redelivery_after_seconds`` is still in flight (acknowledged, not dispatched);
  an older one means the previous attempt died or failed, so it is claimed again (``received_at``
  refreshed) and dispatched once more.

Consequently handlers can run more than once for one event and MUST be idempotent.

It opens its own connection to the same database file as the idempotency store (SQLite handles
several connections) and creates its own table, so the two concerns stay independent. Rows are
removed by ``purge_older_than`` (run by the app lifespan together with the idempotency purge).
"""

import asyncio
import logging
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Literal

from conector_odoo.infrastructure.sqlite import SqliteDatabase

logger = logging.getLogger(__name__)

# ``new``: first sighting, dispatch. ``redeliver``: stale ``received`` row, dispatch again.
# ``duplicate``: already processed or still in flight, acknowledge only.
ClaimOutcome = Literal["new", "redeliver", "duplicate"]
EventStatus = Literal["received", "processed"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS webhook_events (
    event_id TEXT PRIMARY KEY,
    received_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'received' CHECK (status IN ('received', 'processed'))
)
"""


class SqliteWebhookEventStore:
    def __init__(self, path: str, *, clock: Callable[[], datetime] | None = None) -> None:
        # ``claim``/``purge`` use the clock when no explicit ``now`` is given (swappable in tests).
        self.clock: Callable[[], datetime] = clock or (lambda: datetime.now(UTC))
        self._db = SqliteDatabase(path, _SCHEMA)
        self._conn = self._db.conn
        self._migrate()

    async def claim(
        self, event_id: str, *, redelivery_after_seconds: float, now: datetime | None = None
    ) -> ClaimOutcome:
        """Atomically record ``event_id`` as ``received`` and say whether to dispatch it."""
        return await asyncio.to_thread(self._claim, event_id, redelivery_after_seconds, now)

    async def mark_processed(self, event_id: str) -> None:
        await asyncio.to_thread(
            self._db.execute,
            "UPDATE webhook_events SET status = 'processed' WHERE event_id = ?",
            (event_id,),
        )

    async def status(self, event_id: str) -> EventStatus | None:
        """Inspection helper: the event's status, or ``None`` when unknown."""
        return await asyncio.to_thread(self._status, event_id)

    async def purge_older_than(self, hours: float, *, now: datetime | None = None) -> int:
        cutoff = ((now or self.clock()) - timedelta(hours=hours)).isoformat()
        return await asyncio.to_thread(
            self._db.execute, "DELETE FROM webhook_events WHERE received_at < ?", (cutoff,)
        )

    async def close(self) -> None:
        await self._db.close()

    def _migrate(self) -> None:
        """Add ``status`` to a table created before two-phase dedup; its rows count as processed."""
        columns = {row[1] for row in self._conn.execute("PRAGMA table_info(webhook_events)")}
        if "status" not in columns:
            self._conn.execute(
                "ALTER TABLE webhook_events ADD COLUMN status TEXT NOT NULL DEFAULT 'processed'"
            )

    def _claim(
        self, event_id: str, redelivery_after_seconds: float, now: datetime | None
    ) -> ClaimOutcome:
        moment = now or self.clock()
        with self._db.lock:
            try:
                self._conn.execute(
                    "INSERT INTO webhook_events (event_id, received_at, status) "
                    "VALUES (?, ?, 'received')",
                    (event_id, moment.isoformat()),
                )
            except sqlite3.IntegrityError:
                pass
            else:
                return "new"
            row = self._conn.execute(
                "SELECT status, received_at FROM webhook_events WHERE event_id = ?", (event_id,)
            ).fetchone()
            if row is None or row[0] == "processed":
                return "duplicate"
            received_at = _parse_timestamp(row[1])
            if received_at is not None and received_at > moment - timedelta(
                seconds=redelivery_after_seconds
            ):
                return "duplicate"  # previous attempt may still be running
            self._conn.execute(
                "UPDATE webhook_events SET received_at = ? "
                "WHERE event_id = ? AND status = 'received'",
                (moment.isoformat(), event_id),
            )
            return "redeliver"

    def _status(self, event_id: str) -> EventStatus | None:
        with self._db.lock:
            row = self._conn.execute(
                "SELECT status FROM webhook_events WHERE event_id = ?", (event_id,)
            ).fetchone()
        if row is None:
            return None
        return "processed" if row[0] == "processed" else "received"


def _parse_timestamp(value: str) -> datetime | None:
    """Parse a stored timestamp (naive means UTC); ``None`` when unreadable (treated as stale)."""
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        logger.warning("webhook event has an unparsable received_at; treating it as stale")
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
