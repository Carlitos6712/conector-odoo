"""SQLite-backed ``IdempotencyStore`` (stdlib ``sqlite3`` behind ``asyncio.to_thread``).

The HTTP contract lives next to ``infrastructure.api.idempotency.IdempotencyGuard``; this module
documents the storage side:

* Rows move ``in_progress`` -> ``completed`` (replayable response) or -> ``unknown`` (the write may
  have been applied; the key stays blocked). ``release`` deletes the row (no write happened).
* ``begin`` inserts atomically (the primary key makes concurrent claims race-free). An
  ``in_progress`` row older than ``in_progress_timeout_seconds`` was abandoned by a crashed or
  cancelled request and is converted to ``unknown`` rather than re-run.
* Retention: rows are removed by ``purge_older_than`` (the app lifespan runs it at startup and every
  ``idempotency_purge_interval_seconds`` with ``idempotency_ttl_hours``). Stored bodies contain
  customer data (PII), so the TTL bounds how long it lives at rest.
* The database file is created with mode 0600 (and tightened if it already existed); a parent
  directory created by this store is 0700.

One connection guarded by a ``threading.Lock`` (``check_same_thread=False``) serialises access;
the work is tiny, so each call runs in a worker thread only to keep the event loop free.
"""

import asyncio
import json
import os
import sqlite3
import threading
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from conector_odoo.infrastructure.idempotency.store import IdempotencyRecord, Status

_SCHEMA = """
CREATE TABLE IF NOT EXISTS idempotency_keys (
    key TEXT NOT NULL,
    scope TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('in_progress', 'completed', 'unknown')),
    response_status INTEGER,
    response_body TEXT,
    response_headers TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (key, scope)
)
"""
_COLUMNS = "key, scope, request_hash, status, response_status, response_body, response_headers"


class SqliteIdempotencyStore:
    def __init__(self, path: str, *, in_progress_timeout_seconds: float = 300.0) -> None:
        self._timeout = timedelta(seconds=in_progress_timeout_seconds)
        if path != ":memory:":
            _prepare_private_file(Path(path))
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.execute(_SCHEMA)

    async def begin(
        self, key: str, scope: str, request_hash: str, *, now: datetime | None = None
    ) -> IdempotencyRecord | None:
        return await asyncio.to_thread(self._begin, key, scope, request_hash, now)

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

    async def mark_unknown(
        self,
        key: str,
        scope: str,
        response_status: int | None,
        response_body: str | None,
        response_headers: dict[str, str],
    ) -> None:
        await asyncio.to_thread(
            self._execute,
            "UPDATE idempotency_keys SET status = 'unknown', response_status = ?, "
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

    def _begin(
        self, key: str, scope: str, request_hash: str, now: datetime | None
    ) -> IdempotencyRecord | None:
        moment = now or datetime.now(UTC)
        with self._lock:
            while True:
                try:
                    self._conn.execute(
                        "INSERT INTO idempotency_keys "
                        "(key, scope, request_hash, status, created_at) "
                        "VALUES (?, ?, ?, 'in_progress', ?)",
                        (key, scope, request_hash, moment.isoformat()),
                    )
                    return None
                except sqlite3.IntegrityError:
                    existing = self._select(key, scope)
                    if existing is not None:
                        return self._expire_if_abandoned(existing, moment)
                    # deleted between the failed insert and the select: claim it again

    def _expire_if_abandoned(self, record: IdempotencyRecord, now: datetime) -> IdempotencyRecord:
        if record.status != "in_progress":
            return record
        row = self._conn.execute(
            "SELECT created_at FROM idempotency_keys WHERE key = ? AND scope = ?",
            (record.key, record.scope),
        ).fetchone()
        if row is None or datetime.fromisoformat(row[0]) > now - self._timeout:
            return record
        self._conn.execute(
            "UPDATE idempotency_keys SET status = 'unknown' "
            "WHERE key = ? AND scope = ? AND status = 'in_progress'",
            (record.key, record.scope),
        )
        return replace(record, status="unknown")

    def _get(self, key: str, scope: str) -> IdempotencyRecord | None:
        with self._lock:
            return self._select(key, scope)

    def _select(self, key: str, scope: str) -> IdempotencyRecord | None:
        row = self._conn.execute(
            f"SELECT {_COLUMNS} FROM idempotency_keys WHERE key = ? AND scope = ?", (key, scope)
        ).fetchone()
        if row is None:
            return None
        status: Status = row[3] if row[3] in ("completed", "unknown") else "in_progress"
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


def _prepare_private_file(path: Path) -> None:
    """Create the database file as 0600 (parent 0700 if created here); tighten an existing one."""
    parent = path.parent
    if not parent.exists():
        parent.mkdir(parents=True, exist_ok=True)
        parent.chmod(0o700)
    if not path.exists():
        os.close(os.open(path, os.O_RDWR | os.O_CREAT, 0o600))
    path.chmod(0o600)
