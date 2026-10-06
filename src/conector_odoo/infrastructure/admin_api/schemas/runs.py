from datetime import datetime
from typing import Any, Self

from pydantic import BaseModel

from conector_odoo.application.dashboard import DashboardSummary, ScheduledJob
from conector_odoo.domain.sync_runs import RunError, RunStatus, SyncRun


class CountersOut(BaseModel):
    created: int
    updated: int
    skipped: int
    failed: int
    conflicts: int
    processed: int


class RunOut(BaseModel):
    id: int
    job_id: int
    status: RunStatus
    trigger: str
    dry_run: bool
    counters: CountersOut
    started_at: datetime
    finished_at: datetime | None
    duration_seconds: float | None
    heartbeat_at: datetime | None
    parent_run_id: int | None
    error: str | None
    cancel_requested: bool
    error_count: int | None = None

    @classmethod
    def of(cls, run: SyncRun, error_count: int | None = None) -> Self:
        c = run.counters
        return cls(
            id=run.id,
            job_id=run.job_id,
            status=run.status,
            trigger=run.trigger,
            dry_run=run.dry_run,
            counters=CountersOut(
                created=c.created,
                updated=c.updated,
                skipped=c.skipped,
                failed=c.failed,
                conflicts=c.conflicts,
                processed=c.processed,
            ),
            started_at=run.started_at,
            finished_at=run.finished_at,
            duration_seconds=run.duration_seconds,
            heartbeat_at=run.heartbeat_at,
            parent_run_id=run.parent_run_id,
            error=run.error,
            cancel_requested=run.cancel_requested,
            error_count=error_count,
        )


class RunDetailOut(RunOut):
    options: dict[str, Any]
    checkpoint: dict[str, Any]
    sample: list[dict[str, Any]]

    @classmethod
    def detail(cls, run: SyncRun, error_count: int) -> Self:
        base = RunOut.of(run, error_count)
        return cls(
            **base.model_dump(),
            options=dict(run.options),
            checkpoint=dict(run.checkpoint),
            sample=list(run.sample),
        )


class RunListOut(BaseModel):
    items: list[RunOut]


class RunErrorOut(BaseModel):
    id: int
    run_id: int
    record_ref: str | None
    message: str
    side: str
    kind: str
    retryable: bool
    retried: bool
    payload: dict[str, Any] | None

    @classmethod
    def of(cls, error: RunError) -> Self:
        return cls(
            id=error.id,
            run_id=error.run_id,
            record_ref=error.record_ref,
            message=error.message,
            side=error.side.value,
            kind=error.kind.value,
            retryable=error.retryable,
            retried=error.retried,
            payload=error.payload,
        )


class RunErrorListOut(BaseModel):
    items: list[RunErrorOut]
    total: int


class ScheduledJobOut(BaseModel):
    job_id: int
    name: str
    cron: str
    next_fire: datetime | None

    @classmethod
    def of(cls, scheduled: ScheduledJob) -> Self:
        return cls(
            job_id=scheduled.job_id,
            name=scheduled.name,
            cron=scheduled.cron,
            next_fire=scheduled.next_fire,
        )


class DashboardOut(BaseModel):
    profiles: int
    mappings: int
    jobs_total: int
    jobs_enabled: int
    runs_last_24h: dict[str, int]
    active_runs: list[RunOut]
    recent_runs: list[RunOut]
    recent_failures: list[RunOut]
    scheduled: list[ScheduledJobOut]

    @classmethod
    def of(cls, summary: DashboardSummary) -> Self:
        return cls(
            profiles=summary.profiles,
            mappings=summary.mappings,
            jobs_total=summary.jobs_total,
            jobs_enabled=summary.jobs_enabled,
            runs_last_24h=summary.runs_last_24h,
            active_runs=[RunOut.of(r) for r in summary.active_runs],
            recent_runs=[RunOut.of(r) for r in summary.recent_runs],
            recent_failures=[RunOut.of(r) for r in summary.recent_failures],
            scheduled=[ScheduledJobOut.of(s) for s in summary.scheduled],
        )
