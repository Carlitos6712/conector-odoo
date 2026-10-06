"""SQLite ``SyncJobRepository`` over ``sync_jobs`` (migrations 1 and 4).

Trigger and filter are stored as JSON. ``mapping_id`` keeps pointing at one stored mapping version
(the pinned one, or the latest at save time for a job that follows the latest) so a referenced
mapping cannot be deleted; ``reverse_mapping_id`` does the same for the reverse mapping.
"""

import asyncio
import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from conector_odoo.domain.errors import (
    MappingNotFound,
    ProfileNotFound,
    SyncJobInUse,
    SyncJobNameTaken,
    SyncJobNotFound,
)
from conector_odoo.domain.records import RecordFilter
from conector_odoo.domain.sync import (
    ConflictRule,
    Direction,
    EndpointRef,
    ManualTrigger,
    MappingRef,
    ScheduleTrigger,
    SyncJob,
    Trigger,
    TriggerKind,
    WebhookTrigger,
)
from conector_odoo.infrastructure.sync.locks import connection_lock

SyncJobs = list[SyncJob]  # the ``list`` method below shadows the builtin

_COLUMNS = (
    "id, name, source_profile_id, source_resource, target_profile_id, target_resource, "
    "mapping_name, mapping_version, reverse_mapping_name, reverse_mapping_version, direction, "
    "trigger_json, filter_json, batch_size, upsert_key, conflict_rule, source_updated_field, "
    "target_updated_field, enabled"
)


class SqliteSyncJobRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = connection_lock(conn)

    async def add(self, job: SyncJob) -> SyncJob:
        return await asyncio.to_thread(self._add, job)

    async def update(self, job: SyncJob) -> SyncJob:
        return await asyncio.to_thread(self._update, job)

    async def get(self, job_id: int) -> SyncJob | None:
        return await asyncio.to_thread(self._get, job_id)

    async def list(self) -> SyncJobs:
        return await asyncio.to_thread(self._list)

    async def delete(self, job_id: int) -> None:
        await asyncio.to_thread(self._delete, job_id)

    def _add(self, job: SyncJob) -> SyncJob:
        now = datetime.now(UTC).isoformat()
        with self._lock:
            values = self._values(job)
            try:
                cursor = self._conn.execute(
                    "INSERT INTO sync_jobs (name, source_profile_id, source_resource, "
                    "target_profile_id, target_resource, mapping_name, mapping_version, "
                    "reverse_mapping_name, reverse_mapping_version, direction, trigger_json, "
                    "filter_json, batch_size, upsert_key, conflict_rule, source_updated_field, "
                    "target_updated_field, enabled, mapping_id, reverse_mapping_id, created_at, "
                    "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                    "?, ?, ?, ?)",
                    (*values, now, now),
                )
            except sqlite3.IntegrityError as exc:
                raise _translate(exc) from None
            assert cursor.lastrowid is not None
            row = self._select(cursor.lastrowid)
        assert row is not None
        return _to_job(row)

    def _update(self, job: SyncJob) -> SyncJob:
        if job.id is None:
            raise SyncJobNotFound("job has no id")
        with self._lock:
            if self._select(job.id) is None:
                raise SyncJobNotFound(f"sync job {job.id} not found")
            values = self._values(job)
            try:
                self._conn.execute(
                    "UPDATE sync_jobs SET name = ?, source_profile_id = ?, source_resource = ?, "
                    "target_profile_id = ?, target_resource = ?, mapping_name = ?, "
                    "mapping_version = ?, reverse_mapping_name = ?, reverse_mapping_version = ?, "
                    "direction = ?, trigger_json = ?, filter_json = ?, batch_size = ?, "
                    "upsert_key = ?, conflict_rule = ?, source_updated_field = ?, "
                    "target_updated_field = ?, enabled = ?, mapping_id = ?, "
                    "reverse_mapping_id = ?, updated_at = ? WHERE id = ?",
                    (*values, datetime.now(UTC).isoformat(), job.id),
                )
            except sqlite3.IntegrityError as exc:
                raise _translate(exc) from None
            row = self._select(job.id)
        assert row is not None
        return _to_job(row)

    def _get(self, job_id: int) -> SyncJob | None:
        with self._lock:
            row = self._select(job_id)
        return None if row is None else _to_job(row)

    def _list(self) -> SyncJobs:
        with self._lock:
            rows = self._conn.execute(f"SELECT {_COLUMNS} FROM sync_jobs ORDER BY name").fetchall()
        return [_to_job(row) for row in rows]

    def _delete(self, job_id: int) -> None:
        with self._lock:
            if self._select(job_id) is None:
                raise SyncJobNotFound(f"sync job {job_id} not found")
            if self._conn.execute(
                "SELECT 1 FROM sync_runs WHERE job_id = ? LIMIT 1", (job_id,)
            ).fetchone():
                raise SyncJobInUse(f"sync job {job_id} has runs; its history is kept")
            self._conn.execute("DELETE FROM xref WHERE job_id = ?", (job_id,))
            self._conn.execute("DELETE FROM sync_jobs WHERE id = ?", (job_id,))

    def _select(self, job_id: int) -> tuple[Any, ...] | None:
        row: tuple[Any, ...] | None = self._conn.execute(
            f"SELECT {_COLUMNS} FROM sync_jobs WHERE id = ?", (job_id,)
        ).fetchone()
        return row

    def _values(self, job: SyncJob) -> tuple[Any, ...]:
        """Column values in the order of the INSERT; resolves the pinned mapping rows."""
        forward_id = self._mapping_row(job.mapping)
        reverse = job.reverse_mapping
        return (
            job.name,
            job.source.profile_id,
            job.source.resource,
            job.target.profile_id,
            job.target.resource,
            job.mapping.name,
            job.mapping.version,
            reverse.name if reverse else None,
            reverse.version if reverse else None,
            job.direction.value,
            json.dumps(_trigger_to_json(job.trigger)),
            json.dumps(_filter_to_json(job.record_filter)),
            job.batch_size,
            job.upsert_key,
            job.conflict_rule.value,
            job.source_updated_field,
            job.target_updated_field,
            int(job.enabled),
            forward_id,
            self._mapping_row(reverse) if reverse else None,
        )

    def _mapping_row(self, ref: MappingRef) -> int:
        if ref.version is None:
            row = self._conn.execute(
                "SELECT id FROM mappings WHERE name = ? ORDER BY version DESC LIMIT 1", (ref.name,)
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT id FROM mappings WHERE name = ? AND version = ?", (ref.name, ref.version)
            ).fetchone()
        if row is None:
            raise MappingNotFound(f"mapping {ref.name!r} (version {ref.version}) not found")
        return int(row[0])


def _translate(exc: sqlite3.IntegrityError) -> Exception:
    text = str(exc)
    if "UNIQUE" in text and "name" in text:
        return SyncJobNameTaken("another sync job already uses that name")
    return ProfileNotFound("a referenced connection profile does not exist")


def _trigger_to_json(trigger: Trigger) -> dict[str, Any]:
    if isinstance(trigger, ScheduleTrigger):
        return {"kind": trigger.kind.value, "cron": trigger.cron}
    if isinstance(trigger, WebhookTrigger):
        return {"kind": trigger.kind.value, "event_types": list(trigger.event_types)}
    return {"kind": TriggerKind.MANUAL.value}


def _trigger_from_json(raw: str) -> Trigger:
    data = json.loads(raw)
    kind = data.get("kind", TriggerKind.MANUAL.value)
    if kind == TriggerKind.SCHEDULE.value:
        return ScheduleTrigger(data["cron"])
    if kind == TriggerKind.WEBHOOK.value:
        return WebhookTrigger(tuple(data["event_types"]))
    return ManualTrigger()


def _filter_to_json(record_filter: RecordFilter) -> dict[str, Any]:
    return {
        "equals": dict(record_filter.equals),
        "since": record_filter.since.isoformat() if record_filter.since else None,
        "raw": dict(record_filter.raw) if record_filter.raw is not None else None,
    }


def _filter_from_json(raw: str) -> RecordFilter:
    data = json.loads(raw)
    since = data.get("since")
    return RecordFilter(
        equals=data.get("equals") or {},
        since=datetime.fromisoformat(since) if since else None,
        raw=data.get("raw"),
    )


def _to_job(row: tuple[Any, ...]) -> SyncJob:
    reverse = MappingRef(row[8], row[9]) if row[8] else None
    return SyncJob(
        id=row[0],
        name=row[1],
        source=EndpointRef(row[2], row[3]),
        target=EndpointRef(row[4], row[5]),
        mapping=MappingRef(row[6], row[7]),
        reverse_mapping=reverse,
        direction=Direction(row[10]),
        trigger=_trigger_from_json(row[11]),
        record_filter=_filter_from_json(row[12]),
        batch_size=row[13],
        upsert_key=row[14],
        conflict_rule=ConflictRule(row[15]),
        source_updated_field=row[16],
        target_updated_field=row[17],
        enabled=bool(row[18]),
    )
