import asyncio

import pytest

from conector_odoo.application.run_launcher import RunLauncher
from conector_odoo.domain.errors import JobAlreadyRunning, RunNotResumable, SyncJobNotFound
from conector_odoo.domain.sync_runs import RunStatus
from tests.sync.harness import World, build_world


def seed(world: World, n: int = 2) -> None:
    for i in range(1, n + 1):
        world.odoo.seed("customers", {"name": f"Ana {i}", "email": f"ANA{i}@X.com"})


async def test_runner_start_creates_the_run_before_any_work() -> None:
    world = build_world()
    seed(world)
    job = await world.add_job()
    assert job.id is not None
    run = await world.runner.start(job.id)
    assert run.status is RunStatus.RUNNING and run.counters.created == 0
    assert not world.rest.records.get("clients")
    finished = await world.runner.execute(run)
    assert finished.id == run.id and finished.status is RunStatus.SUCCEEDED
    assert finished.counters.created == 2


async def test_trigger_returns_the_run_immediately_and_finishes_in_the_background() -> None:
    world = build_world()
    seed(world)
    job = await world.add_job()
    assert job.id is not None
    launcher = RunLauncher(world.runner)
    run = await launcher.trigger(job.id)
    assert run.status is RunStatus.RUNNING
    await launcher.wait_idle()
    done = await world.runs.get(run.id)
    assert done is not None and done.status is RunStatus.SUCCEEDED
    assert len(world.rest.records["clients"]) == 2


async def test_trigger_refusals_are_raised_before_anything_is_spawned() -> None:
    world = build_world()
    seed(world)
    job = await world.add_job()
    assert job.id is not None
    launcher = RunLauncher(world.runner)
    with pytest.raises(SyncJobNotFound):
        await launcher.trigger(999)
    await launcher.trigger(job.id)
    with pytest.raises(JobAlreadyRunning):
        await launcher.trigger(job.id)
    await launcher.wait_idle()


async def test_dry_run_and_only_records_are_forwarded() -> None:
    world = build_world()
    seed(world)
    job = await world.add_job()
    assert job.id is not None
    launcher = RunLauncher(world.runner)
    run = await launcher.trigger(job.id, dry_run=True)
    await launcher.wait_idle()
    done = await world.runs.get(run.id)
    assert done is not None and done.dry_run and not world.rest.records.get("clients")


async def test_resume_and_retry_failed_run_in_the_background() -> None:
    world = build_world()
    seed(world)
    job = await world.add_job()
    assert job.id is not None
    launcher = RunLauncher(world.runner)
    first = await launcher.trigger(job.id)
    await launcher.wait_idle()
    with pytest.raises(RunNotResumable):  # finished runs cannot be resumed
        await launcher.resume(first.id)
    with pytest.raises(RunNotResumable):  # nothing failed, nothing to retry
        await launcher.retry_failed(first.id)


async def test_close_cancels_in_flight_runs_and_leaves_them_resumable() -> None:
    world = build_world(batch_pause=1.0)
    seed(world, 3)
    job = await world.add_job(batch_size=1)
    assert job.id is not None
    gate = asyncio.Event()

    async def block() -> None:
        gate.set()
        await asyncio.sleep(60)

    world.on_sleep = block
    world.rebuild()
    launcher = RunLauncher(world.runner)
    run = await launcher.trigger(job.id)
    await asyncio.wait_for(gate.wait(), 5)
    await launcher.aclose()
    left = await world.runs.get(run.id)
    assert left is not None and left.status is RunStatus.RUNNING  # stale, resumable
    assert launcher.active == 0


async def test_a_crashing_background_run_is_contained(caplog: pytest.LogCaptureFixture) -> None:
    world = build_world()
    seed(world)
    job = await world.add_job()
    assert job.id is not None
    world.auth_failure = RuntimeError("boom")
    launcher = RunLauncher(world.runner)
    run = await launcher.trigger(job.id)
    await launcher.wait_idle()  # does not raise
    done = await world.runs.get(run.id)
    assert done is not None and done.status is RunStatus.FAILED
    assert "background sync run crashed" in caplog.text
