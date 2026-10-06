"""In-process cron scheduler for sync jobs (asyncio, no framework).

``SyncScheduler`` keeps, per enabled job with a ``ScheduleTrigger``, the next fire time computed
from the injected clock. The loop sleeps until the earliest one, fires every due job through
``TriggerSyncJob`` (``TriggerKind.SCHEDULE``) in its own task and recomputes the job's next fire
time FROM NOW, so ticks missed while the loop was stalled collapse into a single run (no catch-up
storm) and a freshly started scheduler never replays downtime.

* No overlap: a job whose previous scheduled run is still in flight is skipped for that tick; a
  run held by another trigger makes ``TriggerSyncJob`` answer ``ALREADY_RUNNING`` and is skipped
  too (the database guard in the run repository is the authority).
* Isolation: one job failing (or a failed refresh) is logged and never stops the loop or the other
  jobs.
* The job list is reloaded every ``refresh_interval`` seconds, and on demand with ``refresh()``
  (call it after a job is created or edited).
* ``stop()`` cancels the loop and any run in flight. A cancelled run is left ``running`` without a
  heartbeat, which the runner treats as a crashed run (resumable, does not block a new one).

Time (``clock``) and waiting (``sleep``) are injected so tests are deterministic.
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime

from conector_odoo.application.sync_trigger import TriggerOutcome, TriggerSyncJob
from conector_odoo.domain.cron import next_fire
from conector_odoo.domain.ports import SyncJobRepository
from conector_odoo.domain.sync import ScheduleTrigger, TriggerKind

logger = logging.getLogger(__name__)

Clock = Callable[[], datetime]
Sleep = Callable[[float], Awaitable[None]]


class SyncScheduler:
    def __init__(
        self,
        jobs: SyncJobRepository,
        trigger: TriggerSyncJob,
        *,
        clock: Clock,
        sleep: Sleep,
        refresh_interval: float = 60.0,
        max_sleep: float = 30.0,
    ) -> None:
        self._jobs = jobs
        self._trigger = trigger
        self._clock = clock
        self._sleep = sleep
        self._refresh_interval = refresh_interval
        self._max_sleep = max_sleep
        self._cron: dict[int, str] = {}
        self._next: dict[int, datetime] = {}
        self._inflight: dict[int, asyncio.Task[None]] = {}
        self._loop_task: asyncio.Task[None] | None = None
        self._refreshed_at: datetime | None = None

    @property
    def running_jobs(self) -> frozenset[int]:
        return frozenset(job_id for job_id, task in self._inflight.items() if not task.done())

    def next_fire(self, job_id: int) -> datetime | None:
        return self._next.get(job_id)

    async def refresh(self) -> None:
        """Reload the enabled scheduled jobs. A failure keeps the previous schedule."""
        now = self._clock()
        try:
            jobs = await self._jobs.list()
        except Exception:
            logger.exception("scheduler could not reload sync jobs")
            return
        self._refreshed_at = now
        wanted: dict[int, str] = {}
        for job in jobs:
            if job.id is not None and job.enabled and isinstance(job.trigger, ScheduleTrigger):
                wanted[job.id] = job.trigger.cron
        for job_id in set(self._cron) - set(wanted):
            del self._cron[job_id]
            self._next.pop(job_id, None)
        for job_id, cron in wanted.items():
            if self._cron.get(job_id) != cron:
                self._cron[job_id] = cron
                self._next[job_id] = next_fire(cron, now)

    async def tick(self) -> list[int]:
        """Start every job whose fire time has come; return the ids that were started."""
        now = self._clock()
        started: list[int] = []
        for job_id, due in sorted(self._next.items()):
            if due > now:
                continue
            self._next[job_id] = next_fire(self._cron[job_id], now)  # missed ticks collapse
            current = self._inflight.get(job_id)
            if current is not None and not current.done():
                logger.info(
                    "scheduled run skipped: previous run still in flight", extra={"job_id": job_id}
                )
                continue
            self._inflight[job_id] = asyncio.create_task(
                self._fire(job_id), name=f"sync-schedule-{job_id}"
            )
            started.append(job_id)
        return started

    async def wait_idle(self) -> None:
        """Wait for every run in flight (used by tests and graceful drains)."""
        if self._inflight:
            await asyncio.gather(*self._inflight.values(), return_exceptions=True)

    def start(self) -> None:
        if self._loop_task is not None and not self._loop_task.done():
            raise RuntimeError("scheduler already started")
        self._loop_task = asyncio.create_task(self._run_forever(), name="sync-scheduler")

    async def stop(self) -> None:
        """Cancel the loop and the runs in flight; safe to call repeatedly."""
        tasks = [t for t in (self._loop_task, *self._inflight.values()) if t is not None]
        self._loop_task = None
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._inflight.clear()

    async def _fire(self, job_id: int) -> None:
        try:
            result = await self._trigger.execute(job_id, TriggerKind.SCHEDULE)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("scheduled sync run crashed", extra={"job_id": job_id})
            return
        if result.outcome is TriggerOutcome.ALREADY_RUNNING:
            logger.info("scheduled run skipped: job already running", extra={"job_id": job_id})
        elif result.outcome is TriggerOutcome.NOT_FOUND:
            logger.warning("scheduled job no longer exists", extra={"job_id": job_id})
            self._cron.pop(job_id, None)
            self._next.pop(job_id, None)

    async def _run_forever(self) -> None:
        while True:
            try:
                now = self._clock()
                if self._refreshed_at is None or (
                    (now - self._refreshed_at).total_seconds() >= self._refresh_interval
                ):
                    await self.refresh()
                await self.tick()
                await self._sleep(self._delay(self._clock()))
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("scheduler loop error")
                await self._sleep(self._max_sleep)

    def _delay(self, now: datetime) -> float:
        waits = [self._max_sleep]
        if self._next:
            waits.append((min(self._next.values()) - now).total_seconds())
        if self._refreshed_at is not None:
            waits.append(self._refresh_interval - (now - self._refreshed_at).total_seconds())
        return max(0.0, min(waits))
