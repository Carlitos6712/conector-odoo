"""Starts sync runs in the background so a caller (the admin API) gets the run id immediately.

Registering the run (``SyncRunner.start`` / ``prepare_*``) happens inline, so the expected refusals
(unknown job, job already running, run not resumable) are raised to the caller; the long part
(``SyncRunner.execute``) runs in a tracked asyncio task. ``aclose`` cancels the tasks still
running; their runs stay ``running`` without a heartbeat, which the runner treats as a crashed
run: resumable, and it does not block a new run (the same contract as ``SyncScheduler.stop``).
"""

import asyncio
import contextlib
import logging

from conector_odoo.application.sync_runner import SyncRunner
from conector_odoo.domain.errors import RunNotResumable
from conector_odoo.domain.sync import TriggerKind
from conector_odoo.domain.sync_runs import SyncRun

logger = logging.getLogger(__name__)


class RunLauncher:
    def __init__(self, runner: SyncRunner) -> None:
        self._runner = runner
        self._tasks: set[asyncio.Task[None]] = set()

    @property
    def active(self) -> int:
        return sum(1 for task in self._tasks if not task.done())

    async def trigger(
        self,
        job_id: int,
        *,
        dry_run: bool = False,
        only_records: list[str] | None = None,
    ) -> SyncRun:
        """Raises ``SyncJobNotFound`` or ``JobAlreadyRunning``."""
        run = await self._runner.start(
            job_id, trigger=TriggerKind.MANUAL, dry_run=dry_run, only_records=only_records
        )
        self._spawn(run)
        return run

    async def resume(self, run_id: int) -> SyncRun:
        """Raises ``SyncRunNotFound``, ``RunNotResumable`` or ``JobAlreadyRunning``."""
        run = await self._runner.prepare_resume(run_id)
        self._spawn(run)
        return run

    async def retry_failed(self, run_id: int) -> SyncRun:
        """Raises ``SyncRunNotFound`` or ``RunNotResumable``; returns the new linked run."""
        run = await self._runner.prepare_retry(run_id)
        self._spawn(run)
        return run

    async def cancel(self, run_id: int) -> None:
        """Ask an active run to stop at the next batch boundary. Raises ``RunNotResumable`` when
        the run is not active."""
        if not await self._runner.cancel(run_id):
            raise RunNotResumable(f"run {run_id} is not active")

    async def wait_idle(self) -> None:
        """Wait for every background run started so far (used by tests and graceful shutdown)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def aclose(self) -> None:
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task

    def _spawn(self, run: SyncRun) -> None:
        task = asyncio.create_task(self._execute(run), name=f"sync-run-{run.id}")
        self._tasks.add(task)  # a strong reference: the loop only keeps weak ones
        task.add_done_callback(self._tasks.discard)

    async def _execute(self, run: SyncRun) -> None:
        try:
            await self._runner.execute(run)
        except asyncio.CancelledError:
            raise
        except Exception:
            # The runner already marked the run failed before re-raising an unexpected bug.
            logger.exception("background sync run crashed", extra={"run_id": run.id})
