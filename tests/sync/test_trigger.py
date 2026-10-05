import asyncio

from conector_odoo.application.sync_trigger import TriggerOutcome, TriggerSyncJob
from conector_odoo.domain.sync import TriggerKind
from conector_odoo.domain.sync_runs import RunStatus
from tests.sync.harness import World, build_world


def seed(world: World, n: int = 2) -> None:
    for i in range(1, n + 1):
        world.odoo.seed("customers", {"name": f"Ana {i}", "email": f"ANA{i}@X.com"})


async def test_manual_trigger_runs_the_job_and_returns_the_run() -> None:
    world = build_world()
    seed(world)
    job = await world.add_job()
    assert job.id is not None
    result = await TriggerSyncJob(world.runner).execute(job.id, TriggerKind.MANUAL)
    assert result.outcome is TriggerOutcome.COMPLETED
    assert result.run is not None
    assert (result.run.status, result.run.trigger) == (RunStatus.SUCCEEDED, "manual")
    assert result.run.counters.created == 2


async def test_trigger_dry_run_writes_nothing() -> None:
    world = build_world()
    seed(world)
    job = await world.add_job()
    assert job.id is not None
    result = await TriggerSyncJob(world.runner).execute(job.id, TriggerKind.MANUAL, dry_run=True)
    assert result.run is not None and result.run.dry_run
    assert not world.rest.records.get("clients")


async def test_trigger_reports_already_running_without_raising() -> None:
    world = build_world()
    seed(world)
    job = await world.add_job()
    assert job.id is not None
    trigger = TriggerSyncJob(world.runner)
    inner: list[object] = []

    async def during_run() -> None:
        inner.append(await trigger.execute(job.id or 0, TriggerKind.MANUAL))

    world.on_sleep = during_run
    world.config = world.config.__class__(batch_pause=1.0)
    world.rebuild()
    trigger = TriggerSyncJob(world.runner)
    first = await trigger.execute(job.id, TriggerKind.MANUAL)
    assert first.outcome is TriggerOutcome.COMPLETED
    [second] = inner
    assert second.outcome is TriggerOutcome.ALREADY_RUNNING  # type: ignore[attr-defined]
    assert second.run is None  # type: ignore[attr-defined]


async def test_trigger_unknown_job_is_a_typed_result() -> None:
    world = build_world()
    result = await TriggerSyncJob(world.runner).execute(999, TriggerKind.MANUAL)
    assert result.outcome is TriggerOutcome.NOT_FOUND and result.run is None


async def test_trigger_does_not_block_the_event_loop() -> None:
    world = build_world()
    seed(world, 3)
    job = await world.add_job()
    assert job.id is not None
    ticks = 0

    async def ticker() -> None:
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0)

    task = asyncio.create_task(ticker())
    await TriggerSyncJob(world.runner).execute(job.id, TriggerKind.MANUAL)
    task.cancel()
    assert ticks > 1
