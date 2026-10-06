"""Read model for the admin dashboard: counts, recent activity and the schedule."""

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from conector_odoo.domain.ports import (
    ConnectionProfileRepository,
    MappingRepository,
    SyncJobRepository,
    SyncRunRepository,
)
from conector_odoo.domain.sync import ScheduleTrigger
from conector_odoo.domain.sync_runs import RunFilter, RunStatus, SyncRun

RECENT_RUNS = 10
RECENT_FAILURES = 5
WINDOW = timedelta(hours=24)
_FAILURE_SCAN = 25  # failures read per status before superseded ones are dropped
_SUCCESS_SCAN = 10  # newest successes read per job to find a real (non-dry) one
_WINDOW_RUN_CAP = 1000  # bounds the aggregation; busier systems see "at least" this many


@dataclass(frozen=True, slots=True)
class ScheduledJob:
    job_id: int
    name: str
    cron: str
    next_fire: datetime | None


@dataclass(frozen=True, slots=True)
class DashboardSummary:
    profiles: int
    mappings: int
    jobs_total: int
    jobs_enabled: int
    runs_last_24h: dict[str, int]
    active_runs: list[SyncRun]
    recent_runs: list[SyncRun]
    recent_failures: list[SyncRun]
    scheduled: list[ScheduledJob]


class GetDashboard:
    def __init__(
        self,
        profiles: ConnectionProfileRepository,
        mappings: MappingRepository,
        jobs: SyncJobRepository,
        runs: SyncRunRepository,
        clock: Callable[[], datetime],
        next_fire: Callable[[int], datetime | None],
    ) -> None:
        self._profiles = profiles
        self._mappings = mappings
        self._jobs = jobs
        self._runs = runs
        self._clock = clock
        self._next_fire = next_fire

    async def execute(self) -> DashboardSummary:
        now = self._clock()
        jobs = await self._jobs.list()
        window = await self._runs.list_runs(
            RunFilter(started_from=now - WINDOW), limit=_WINDOW_RUN_CAP
        )
        counts = Counter(run.status.value for run in window)
        active: list[SyncRun] = []
        for status in (RunStatus.RUNNING, RunStatus.QUEUED):
            active.extend(await self._runs.list_runs(RunFilter(status=status), limit=50))
        failures: list[SyncRun] = []
        for status in (RunStatus.FAILED, RunStatus.PARTIAL):
            failures.extend(
                await self._runs.list_runs(RunFilter(status=status), limit=_FAILURE_SCAN)
            )
        failures = await self._unresolved(failures)
        failures.sort(key=lambda run: run.started_at, reverse=True)
        return DashboardSummary(
            profiles=len(await self._profiles.list()),
            mappings=len(await self._mappings.list_latest()),
            jobs_total=len(jobs),
            jobs_enabled=sum(1 for job in jobs if job.enabled),
            runs_last_24h={status.value: counts.get(status.value, 0) for status in RunStatus},
            active_runs=active,
            recent_runs=await self._runs.list_runs(RunFilter(), limit=RECENT_RUNS),
            recent_failures=failures[:RECENT_FAILURES],
            scheduled=[
                ScheduledJob(job.id, job.name, job.trigger.cron, self._next_fire(job.id))
                for job in jobs
                if job.enabled and job.id is not None and isinstance(job.trigger, ScheduleTrigger)
            ],
        )

    async def _unresolved(self, failures: list[SyncRun]) -> list[SyncRun]:
        """Drop failures a later real (non-dry) successful run of the same job has superseded."""
        latest_success: dict[int, datetime | None] = {}
        for job_id in {run.job_id for run in failures}:
            successes = await self._runs.list_runs(
                RunFilter(job_id=job_id, status=RunStatus.SUCCEEDED), limit=_SUCCESS_SCAN
            )
            real = [run.started_at for run in successes if not run.dry_run]
            latest_success[job_id] = max(real, default=None)
        return [
            run
            for run in failures
            if (done := latest_success[run.job_id]) is None or done <= run.started_at
        ]
