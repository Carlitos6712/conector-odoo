"""SQLite ``SyncRunRepository`` and ``XRefRepository`` over ``sync_runs``, ``run_errors`` and
``xref`` (migrations 1 and 4).

Timestamps are stored as UTC ISO-8601 text, so string comparison orders them chronologically.
The admin connection is autocommit; multi-statement writes use an explicit transaction.
"""

import asyncio
import json
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from conector_odoo.domain.errors import JobAlreadyRunning, SyncJobNotFound, SyncRunNotFound
from conector_odoo.domain.sync_runs import (
    ErrorKind,
    RunCounters,
    RunError,
    RunErrorData,
    RunFilter,
    RunStatus,
    Side,
    SyncRun,
    XRef,
)
from conector_odoo.infrastructure.sync.locks import connection_lock

SyncRuns = list[SyncRun]
RunErrors = list[RunError]
XRefs = list[XRef]

_RUN_COLUMNS = (
    "id, job_id, status, trigger, dry_run, created, updated, skipped, failed, conflicts, "
    "started_at, finished_at, heartbeat_at, checkpoint_json, parent_run_id, options_json, error, "
    "sample_json, cancel_requested"
)
_ERROR_COLUMNS = "id, run_id, record_ref, message, side, kind, retryable, retried, payload_json"
_XREF_COLUMNS = "job_id, resource, source_id, target_id, content_hash, reverse_hash, updated_at"


def _ts(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


class SqliteSyncRunRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = connection_lock(conn)

    async def create(
        self,
        job_id: int,
        trigger: str,
        *,
        dry_run: bool,
        started_at: datetime,
        stale_before: datetime,
        parent_run_id: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> SyncRun:
        return await asyncio.to_thread(
            self._create, job_id, trigger, dry_run, started_at, stale_before, parent_run_id, options
        )

    async def get(self, run_id: int) -> SyncRun | None:
        return await asyncio.to_thread(self._get, run_id)

    async def reopen(
        self, run_id: int, *, heartbeat_at: datetime, stale_before: datetime
    ) -> SyncRun:
        return await asyncio.to_thread(self._reopen, run_id, heartbeat_at, stale_before)

    async def save_progress(
        self,
        run_id: int,
        counters: RunCounters,
        checkpoint: dict[str, Any],
        heartbeat_at: datetime,
    ) -> None:
        await asyncio.to_thread(self._save_progress, run_id, counters, checkpoint, heartbeat_at)

    async def finish(
        self,
        run_id: int,
        status: RunStatus,
        finished_at: datetime,
        counters: RunCounters,
        *,
        error: str | None = None,
        sample: Sequence[dict[str, Any]] = (),
        warnings: Sequence[str] = (),
    ) -> None:
        await asyncio.to_thread(
            self._finish, run_id, status, finished_at, counters, error, sample, warnings
        )

    async def request_cancel(self, run_id: int) -> bool:
        return await asyncio.to_thread(self._request_cancel, run_id)

    async def is_cancel_requested(self, run_id: int) -> bool:
        return await asyncio.to_thread(self._is_cancel_requested, run_id)

    async def add_errors(self, run_id: int, errors: Sequence[RunErrorData]) -> None:
        await asyncio.to_thread(self._add_errors, run_id, errors)

    async def list_runs(self, run_filter: RunFilter, limit: int = 50, offset: int = 0) -> SyncRuns:
        return await asyncio.to_thread(self._list_runs, run_filter, limit, offset)

    async def list_errors(
        self, run_id: int, limit: int = 100, offset: int = 0, *, only_unretried: bool = False
    ) -> RunErrors:
        return await asyncio.to_thread(self._list_errors, run_id, limit, offset, only_unretried)

    async def count_errors(self, run_id: int) -> int:
        return await asyncio.to_thread(self._count_errors, run_id)

    async def mark_errors_retried(self, run_id: int, side: str, record_refs: Sequence[str]) -> None:
        await asyncio.to_thread(self._mark_retried, run_id, side, record_refs)

    # -- blocking implementations ----------------------------------------------------------

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    def _active_run_exists(self, job_id: int, stale_before: datetime, *, exclude: int = 0) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM sync_runs WHERE job_id = ? AND id != ? AND status IN "
            "('queued', 'running') AND COALESCE(heartbeat_at, started_at) >= ? LIMIT 1",
            (job_id, exclude, _ts(stale_before)),
        ).fetchone()
        return row is not None

    def _create(
        self,
        job_id: int,
        trigger: str,
        dry_run: bool,
        started_at: datetime,
        stale_before: datetime,
        parent_run_id: int | None,
        options: dict[str, Any] | None,
    ) -> SyncRun:
        with self._transaction():
            if (
                self._conn.execute("SELECT 1 FROM sync_jobs WHERE id = ?", (job_id,)).fetchone()
                is None
            ):
                raise SyncJobNotFound(f"sync job {job_id} not found")
            if self._active_run_exists(job_id, stale_before):
                raise JobAlreadyRunning(f"sync job {job_id} already has an active run")
            cursor = self._conn.execute(
                "INSERT INTO sync_runs (job_id, status, trigger, dry_run, started_at, "
                "heartbeat_at, parent_run_id, options_json) "
                "VALUES (?, 'running', ?, ?, ?, ?, ?, ?)",
                (
                    job_id,
                    trigger,
                    int(dry_run),
                    _ts(started_at),
                    _ts(started_at),
                    parent_run_id,
                    json.dumps(options or {}),
                ),
            )
            run_id = cursor.lastrowid
        assert run_id is not None
        run = self._get(run_id)
        assert run is not None
        return run

    def _get(self, run_id: int) -> SyncRun | None:
        with self._lock:
            row = self._conn.execute(
                f"SELECT {_RUN_COLUMNS} FROM sync_runs WHERE id = ?", (run_id,)
            ).fetchone()
        return None if row is None else _to_run(row)

    def _reopen(self, run_id: int, heartbeat_at: datetime, stale_before: datetime) -> SyncRun:
        with self._transaction():
            row = self._conn.execute(
                "SELECT job_id FROM sync_runs WHERE id = ?", (run_id,)
            ).fetchone()
            if row is None:
                raise SyncRunNotFound(f"sync run {run_id} not found")
            if self._active_run_exists(row[0], stale_before, exclude=run_id):
                raise JobAlreadyRunning(f"sync job {row[0]} already has an active run")
            self._conn.execute(
                "UPDATE sync_runs SET status = 'running', finished_at = NULL, error = NULL, "
                "cancel_requested = 0, heartbeat_at = ? WHERE id = ?",
                (_ts(heartbeat_at), run_id),
            )
        run = self._get(run_id)
        assert run is not None
        return run

    def _save_progress(
        self, run_id: int, counters: RunCounters, checkpoint: dict[str, Any], heartbeat_at: datetime
    ) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE sync_runs SET created = ?, updated = ?, skipped = ?, failed = ?, "
                "conflicts = ?, checkpoint_json = ?, heartbeat_at = ? WHERE id = ?",
                (
                    counters.created,
                    counters.updated,
                    counters.skipped,
                    counters.failed,
                    counters.conflicts,
                    json.dumps(checkpoint),
                    _ts(heartbeat_at),
                    run_id,
                ),
            )

    def _finish(
        self,
        run_id: int,
        status: RunStatus,
        finished_at: datetime,
        counters: RunCounters,
        error: str | None,
        sample: Sequence[dict[str, Any]],
        warnings: Sequence[str],
    ) -> None:
        with self._lock:
            if warnings:
                self._conn.execute(
                    "UPDATE sync_runs SET options_json = json_set(options_json, '$.warnings', "
                    "json(?)) WHERE id = ?",
                    (json.dumps(list(warnings)), run_id),
                )
            self._conn.execute(
                "UPDATE sync_runs SET status = ?, finished_at = ?, heartbeat_at = ?, created = ?, "
                "updated = ?, skipped = ?, failed = ?, conflicts = ?, error = ?, sample_json = ? "
                "WHERE id = ?",
                (
                    status.value,
                    _ts(finished_at),
                    _ts(finished_at),
                    counters.created,
                    counters.updated,
                    counters.skipped,
                    counters.failed,
                    counters.conflicts,
                    error,
                    json.dumps(list(sample), default=str),
                    run_id,
                ),
            )

    def _request_cancel(self, run_id: int) -> bool:
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE sync_runs SET cancel_requested = 1 WHERE id = ? AND status IN "
                "('queued', 'running')",
                (run_id,),
            )
        return cursor.rowcount > 0

    def _is_cancel_requested(self, run_id: int) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT cancel_requested FROM sync_runs WHERE id = ?", (run_id,)
            ).fetchone()
        return bool(row and row[0])

    def _add_errors(self, run_id: int, errors: Sequence[RunErrorData]) -> None:
        if not errors:
            return
        with self._transaction():
            self._conn.executemany(
                "INSERT INTO run_errors (run_id, record_ref, message, payload_json, side, kind, "
                "retryable) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        run_id,
                        e.record_ref,
                        e.message,
                        None if e.payload is None else json.dumps(e.payload, default=str),
                        e.side.value,
                        e.kind.value,
                        int(e.retryable),
                    )
                    for e in errors
                ],
            )

    def _list_runs(self, run_filter: RunFilter, limit: int, offset: int) -> SyncRuns:
        clauses: list[str] = []
        params: list[Any] = []
        if run_filter.job_id is not None:
            clauses.append("job_id = ?")
            params.append(run_filter.job_id)
        if run_filter.status is not None:
            clauses.append("status = ?")
            params.append(run_filter.status.value)
        if run_filter.started_from is not None:
            clauses.append("started_at >= ?")
            params.append(_ts(run_filter.started_from))
        if run_filter.started_to is not None:
            clauses.append("started_at <= ?")
            params.append(_ts(run_filter.started_to))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {_RUN_COLUMNS} FROM sync_runs {where} ORDER BY started_at DESC, id DESC "
                "LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
        return [_to_run(row) for row in rows]

    def _list_errors(self, run_id: int, limit: int, offset: int, only_unretried: bool) -> RunErrors:
        extra = " AND retried = 0" if only_unretried else ""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {_ERROR_COLUMNS} FROM run_errors WHERE run_id = ?{extra} "
                "ORDER BY id LIMIT ? OFFSET ?",
                (run_id, limit, offset),
            ).fetchall()
        return [_to_error(row) for row in rows]

    def _count_errors(self, run_id: int) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM run_errors WHERE run_id = ?", (run_id,)
            ).fetchone()
        return int(row[0])

    def _mark_retried(self, run_id: int, side: str, record_refs: Sequence[str]) -> None:
        if not record_refs:
            return
        with self._transaction():
            self._conn.executemany(
                "UPDATE run_errors SET retried = 1 "
                "WHERE run_id = ? AND side = ? AND record_ref = ?",
                [(run_id, side, ref) for ref in record_refs],
            )


class SqliteXRefRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = connection_lock(conn)

    async def get_target(self, job_id: int, resource: str, source_id: str) -> XRef | None:
        return await asyncio.to_thread(self._one, "source_id", job_id, resource, source_id)

    async def get_source(self, job_id: int, resource: str, target_id: str) -> XRef | None:
        return await asyncio.to_thread(self._one, "target_id", job_id, resource, target_id)

    async def upsert(self, xref: XRef) -> None:
        await asyncio.to_thread(self._upsert, xref)

    async def list(
        self, job_id: int, resource: str | None = None, limit: int = 100, offset: int = 0
    ) -> XRefs:
        return await asyncio.to_thread(self._list, job_id, resource, limit, offset)

    async def forget_target(self, profile_id: int, resource: str, target_id: str) -> int:
        return await asyncio.to_thread(self._forget_target, profile_id, resource, target_id)

    async def forget_source(self, profile_id: int, resource: str, source_id: str) -> int:
        return await asyncio.to_thread(self._forget_source, profile_id, resource, source_id)

    async def forget(self, job_id: int, resource: str, source_id: str) -> int:
        return await asyncio.to_thread(self._forget, job_id, resource, source_id)

    def _forget_source(self, profile_id: int, resource: str, source_id: str) -> int:
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM xref WHERE source_id = ? AND job_id IN "
                "(SELECT id FROM sync_jobs WHERE source_profile_id = ? AND source_resource = ?)",
                (source_id, profile_id, resource),
            )
            return cursor.rowcount

    def _forget(self, job_id: int, resource: str, source_id: str) -> int:
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM xref WHERE job_id = ? AND resource = ? AND source_id = ?",
                (job_id, resource, source_id),
            )
            return cursor.rowcount

    def _forget_target(self, profile_id: int, resource: str, target_id: str) -> int:
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM xref WHERE target_id = ? AND job_id IN "
                "(SELECT id FROM sync_jobs WHERE target_profile_id = ? AND target_resource = ?)",
                (target_id, profile_id, resource),
            )
            return cursor.rowcount

    def _one(self, column: str, job_id: int, resource: str, value: str) -> XRef | None:
        with self._lock:
            row = self._conn.execute(
                f"SELECT {_XREF_COLUMNS} FROM xref WHERE job_id = ? AND resource = ? "
                f"AND {column} = ? ORDER BY id LIMIT 1",
                (job_id, resource, value),
            ).fetchone()
        return None if row is None else _to_xref(row)

    def _upsert(self, xref: XRef) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO xref (job_id, resource, source_id, target_id, content_hash, "
                "reverse_hash, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (job_id, resource, source_id) DO UPDATE SET "
                "target_id = excluded.target_id, content_hash = excluded.content_hash, "
                "reverse_hash = excluded.reverse_hash, updated_at = excluded.updated_at",
                (
                    xref.job_id,
                    xref.resource,
                    xref.source_id,
                    xref.target_id,
                    xref.content_hash,
                    xref.reverse_hash,
                    _ts(xref.synced_at),
                ),
            )

    def _list(self, job_id: int, resource: str | None, limit: int, offset: int) -> XRefs:
        clause = "" if resource is None else " AND resource = ?"
        params: tuple[Any, ...] = (job_id,) if resource is None else (job_id, resource)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {_XREF_COLUMNS} FROM xref WHERE job_id = ?{clause} ORDER BY id "
                "LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
        return [_to_xref(row) for row in rows]


def _to_run(row: tuple[Any, ...]) -> SyncRun:
    return SyncRun(
        id=row[0],
        job_id=row[1],
        status=RunStatus(row[2]),
        trigger=row[3],
        dry_run=bool(row[4]),
        counters=RunCounters(row[5], row[6], row[7], row[8], row[9]),
        started_at=datetime.fromisoformat(row[10]),
        finished_at=datetime.fromisoformat(row[11]) if row[11] else None,
        heartbeat_at=datetime.fromisoformat(row[12]) if row[12] else None,
        checkpoint=json.loads(row[13]),
        parent_run_id=row[14],
        options=json.loads(row[15]),
        error=row[16],
        sample=json.loads(row[17]),
        cancel_requested=bool(row[18]),
    )


def _to_error(row: tuple[Any, ...]) -> RunError:
    return RunError(
        id=row[0],
        run_id=row[1],
        record_ref=row[2],
        message=row[3],
        side=Side(row[4]),
        kind=ErrorKind(row[5]),
        retryable=bool(row[6]),
        retried=bool(row[7]),
        payload=None if row[8] is None else json.loads(row[8]),
    )


def _to_xref(row: tuple[Any, ...]) -> XRef:
    return XRef(
        job_id=row[0],
        resource=row[1],
        source_id=row[2],
        target_id=row[3],
        content_hash=row[4],
        reverse_hash=row[5],
        synced_at=datetime.fromisoformat(row[6]),
    )
