"""Use case shared by every trigger (manual, schedule, webhook): run a job once.

``SyncRunner.run`` is a coroutine over async repositories and endpoints, so a run never blocks the
event loop; no thread is needed. Expected refusals become a typed ``TriggerResult`` instead of
exceptions, so a trigger source never crashes because a job vanished or is already running.
"""

from dataclasses import dataclass
from enum import StrEnum

from conector_odoo.application.sync_runner import SyncRunner
from conector_odoo.domain.errors import JobAlreadyRunning, SyncJobNotFound
from conector_odoo.domain.sync import TriggerKind
from conector_odoo.domain.sync_runs import SyncRun


class TriggerOutcome(StrEnum):
    COMPLETED = "completed"  # the run finished; inspect ``run.status`` for the verdict
    ALREADY_RUNNING = "already_running"
    NOT_FOUND = "not_found"


@dataclass(frozen=True, slots=True)
class TriggerResult:
    outcome: TriggerOutcome
    run: SyncRun | None = None


class TriggerSyncJob:
    def __init__(self, runner: SyncRunner) -> None:
        self._runner = runner

    async def execute(
        self,
        job_id: int,
        trigger: TriggerKind = TriggerKind.MANUAL,
        *,
        dry_run: bool = False,
        only_records: list[str] | None = None,
    ) -> TriggerResult:
        """Run the job and wait for it to end. An unexpected runner bug still propagates."""
        try:
            run = await self._runner.run(
                job_id, trigger=trigger, dry_run=dry_run, only_records=only_records
            )
        except JobAlreadyRunning:
            return TriggerResult(TriggerOutcome.ALREADY_RUNNING)
        except SyncJobNotFound:
            return TriggerResult(TriggerOutcome.NOT_FOUND)
        return TriggerResult(TriggerOutcome.COMPLETED, run)
