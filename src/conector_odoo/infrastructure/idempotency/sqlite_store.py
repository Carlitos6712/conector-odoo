"""SQLite-backed ``IdempotencyStore`` (stdlib ``sqlite3`` behind ``asyncio.to_thread``).

Idempotency semantics (enforced by ``infrastructure.api.idempotency.IdempotencyGuard``):

* ``Idempotency-Key`` is optional on ``POST /customers``, ``POST /sale-orders`` and
  ``POST /sale-orders/{id}/confirm`` (max 255 characters, otherwise 422). Without it the
  request behaves exactly as before.
* The key is scoped by ``"METHOD path"`` (for example ``"POST /customers"``): the same key on
  another endpoint is an independent request.
* First request: an ``in_progress`` row is inserted atomically (``INSERT``; the primary key
  makes concurrent claims race-free). On a 2xx result, including the ``202 created_but_unreadable``
  answer (the record exists in Odoo), the status, body and headers are stored as ``completed``.
  Any other outcome deletes the row so the client may retry.
* Same key, same request hash, ``completed``: the stored response is replayed with
  ``Idempotent-Replayed: true``.
* Same key, different request hash: 422 ``idempotency_key_reused``.
* Same key while ``in_progress``: 409 ``idempotency_in_progress``.
* The request hash is the SHA-256 of the canonical JSON of the validated body, path params and
  query params.

Rows left ``in_progress`` by a crash (or a cancelled request, which is deliberately not released
because the write may have happened) block the key with 409 until ``purge_older_than`` removes
them; call it periodically (no scheduler is built in).

One connection guarded by a ``threading.Lock`` (``check_same_thread=False``) serialises access;
the work is tiny, so each call runs in a worker thread only to keep the event loop free.
"""

import asyncio
import json
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from conector_odoo.infrastructure.idempotency.store import IdempotencyRecord, Status

_SCHEMA = """
CREATE TABLE IF NOT EXISTS idempotency_keys (
    key TEXT NOT NULL,
    scope TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('in_progress', 'completed')),
    response_status INTEGER,
    response_body TEXT,
    response_headers TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (key, scope)
)
"""
_COLUMNS = "key, scope, request_hash, status, response_status, response_body, response_headers"


class SqliteIdempotencyStore:
    def __init__(self, path: str) -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.execute(_SCHEMA)

    async def begin(self, key: str, scope: str, request_hash: str) -> IdempotencyRecord | None:
        return await asyncio.to_thread(self._begin, key, scope, request_hash)

    async def get(self, key: str, scope: str) -> IdempotencyRecord | None:
        return await asyncio.to_thread(self._get, key, scope)

    async def complete(
        self,
        key: str,
        scope: str,
        response_status: int,
        response_body: str,
        response_headers: dict[str, str],
    ) -> None:
        await asyncio.to_thread(
            self._execute,
            "UPDATE idempotency_keys SET status = 'completed', response_status = ?, "
            "response_body = ?, response_headers = ? WHERE key = ? AND scope = ?",
            (response_status, response_body, json.dumps(response_headers), key, scope),
        )

    async def release(self, key: str, scope: str) -> None:
        await asyncio.to_thread(
            self._execute, "DELETE FROM idempotency_keys WHERE key = ? AND scope = ?", (key, scope)
        )

    async def purge_older_than(self, hours: float, *, now: datetime | None = None) -> int:
        cutoff = ((now or datetime.now(UTC)) - timedelta(hours=hours)).isoformat()
        return await asyncio.to_thread(
            self._execute, "DELETE FROM idempotency_keys WHERE created_at < ?", (cutoff,)
        )

    async def close(self) -> None:
        await asyncio.to_thread(self._close)

    def _begin(self, key: str, scope: str, request_hash: str) -> IdempotencyRecord | None:
        with self._lock:
            while True:
                try:
                    self._conn.execute(
                        "INSERT INTO idempotency_keys "
                        "(key, scope, request_hash, status, created_at) "
                        "VALUES (?, ?, ?, 'in_progress', ?)",
                        (key, scope, request_hash, datetime.now(UTC).isoformat()),
                    )
                    return None
                except sqlite3.IntegrityError:
                    existing = self._select(key, scope)
                    if existing is not None:
                        return existing
                    # deleted between the failed insert and the select: claim it again

    def _get(self, key: str, scope: str) -> IdempotencyRecord | None:
        with self._lock:
            return self._select(key, scope)

    def _select(self, key: str, scope: str) -> IdempotencyRecord | None:
        row = self._conn.execute(
            f"SELECT {_COLUMNS} FROM idempotency_keys WHERE key = ? AND scope = ?", (key, scope)
        ).fetchone()
        if row is None:
            return None
        status: Status = "completed" if row[3] == "completed" else "in_progress"
        return IdempotencyRecord(
            key=row[0],
            scope=row[1],
            request_hash=row[2],
            status=status,
            response_status=row[4],
            response_body=row[5],
            response_headers=json.loads(row[6]) if row[6] else {},
        )

    def _execute(self, sql: str, params: tuple[Any, ...]) -> int:
        with self._lock:
            return self._conn.execute(sql, params).rowcount

    def _close(self) -> None:
        with self._lock:
            self._conn.close()
