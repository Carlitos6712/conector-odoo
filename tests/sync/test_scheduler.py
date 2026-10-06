import asyncio
import dataclasses
from datetime import UTC, datetime

import pytest

from conector_odoo.application.scheduler import SyncScheduler
from conector_odoo.application.sync_trigger import TriggerSyncJob
from conector_odoo.domain.sync import ScheduleTrigger, WebhookTrigger
from conector_odoo.domain.sync_runs import RunFilter
from tests.sync.harness import T0, World, build_world

_ALL = RunFilter()
EVERY_5 = ScheduleTrigger("*/5 * * * *")  # T0 is 12:00, so fires at 12:05, 12:10...


class Env:
    def __init__(self, world: World, **kwargs: float) -> None:
        self.world = world
        self.sleeps: list[float] = []

        async def sleep(seconds: float) -> None:
            self.sleeps.append(seconds)
            self.world.clock.advance(seconds=seconds)
            await asyncio.sleep(0)

        self.sleep = sleep
        self.scheduler = SyncScheduler(
            world.jobs, TriggerSyncJob(world.runner), clock=world.clock, sleep=sleep, **kwargs
        )

    async def runs(self) -> list[tuple[int, str]]:
        return [(r.job_id, r.trigger) for r in reversed(await self.world.runs.list_runs(_ALL, 50))]


async def make(trigger: ScheduleTrigger = EVERY_5, **kwargs: float) -> tuple[Env, int]:
    world = build_world()
    world.odoo.seed("customers", {"name": "Ana", "email": "A@X.com"})
    job = await world.add_job(trigger=trigger)
    assert job.id is not None
    env = Env(world, **kwargs)
    await env.scheduler.refresh()
    return env, job.id


async def test_fires_a_due_job_once_with_schedule_trigger() -> None:
    env, job_id = await make()
    assert await env.scheduler.tick() == []  # 12:00, nothing due
    env.world.clock.advance(minutes=5)
    assert await env.scheduler.tick() == [job_id]
    await env.scheduler.wait_idle()
    assert await env.runs() == [(job_id, "schedule")]
    assert await env.scheduler.tick() == []  # same instant: not fired twice


async def test_missed_ticks_after_a_long_pause_fire_only_once() -> None:
    env, job_id = await make()
    env.world.clock.advance(hours=3)  # 36 missed ticks
    assert await env.scheduler.tick() == [job_id]
    await env.scheduler.wait_idle()
    assert await env.scheduler.tick() == []
    assert len(await env.runs()) == 1
    assert env.scheduler.next_fire(job_id) == datetime(2026, 5, 1, 15, 5, tzinfo=UTC)


async def test_new_scheduler_does_not_catch_up_on_downtime() -> None:
    env, _ = await make()
    env.world.clock.advance(hours=2)
    fresh = SyncScheduler(
        env.world.jobs, TriggerSyncJob(env.world.runner), clock=env.world.clock, sleep=env.sleep
    )
    await fresh.refresh()
    assert await fresh.tick() == []


async def test_skips_when_the_job_is_still_running() -> None:
    env, job_id = await make()
    gate = asyncio.Event()
    release = asyncio.Event()
    original = env.world.runner.run

    async def slow_run(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        gate.set()
        await release.wait()
        return await original(*args, **kwargs)  # type: ignore[arg-type]

    env.world.runner.run = slow_run  # type: ignore[method-assign]
    env.world.clock.advance(minutes=5)
    assert await env.scheduler.tick() == [job_id]
    await gate.wait()
    env.world.clock.advance(minutes=5)
    assert await env.scheduler.tick() == []  # overlap prevented, tick consumed
    release.set()
    await env.scheduler.wait_idle()
    assert len(await env.runs()) == 1


async def test_skips_when_another_trigger_holds_the_job() -> None:
    env, job_id = await make()
    await env.world.runs.create(
        job_id, "manual", dry_run=False, started_at=T0, stale_before=T0.replace(year=2020)
    )
    env.world.clock.advance(minutes=5)
    await env.scheduler.tick()
    await env.scheduler.wait_idle()
    assert [r for r in await env.runs() if r[1] == "schedule"] == []


async def test_a_failing_job_does_not_stop_the_others() -> None:
    env, first = await make()
    original_job = await env.world.jobs.get(first)
    assert original_job is not None
    second = await env.world.jobs.add(dataclasses.replace(original_job, id=None, name="other"))
    await env.scheduler.refresh()
    original = env.world.runner.run

    async def flaky(job_id: int, **kwargs: object):  # type: ignore[no-untyped-def]
        if job_id == first:
            raise RuntimeError("boom")
        return await original(job_id, **kwargs)  # type: ignore[arg-type]

    env.world.runner.run = flaky  # type: ignore[method-assign]
    env.world.clock.advance(minutes=5)
    assert sorted(await env.scheduler.tick()) == sorted([first, second.id or 0])
    await env.scheduler.wait_idle()
    assert await env.runs() == [(second.id, "schedule")]


async def test_refresh_picks_up_changes() -> None:
    env, job_id = await make()
    job = await env.world.jobs.get(job_id)
    assert job is not None
    # disabled job is dropped
    await env.world.jobs.update(dataclasses.replace(job, enabled=False))
    await env.scheduler.refresh()
    assert env.scheduler.next_fire(job_id) is None
    # webhook-only trigger is not scheduled
    await env.world.jobs.update(
        dataclasses.replace(job, trigger=WebhookTrigger(("partner.created",)))
    )
    await env.scheduler.refresh()
    assert env.scheduler.next_fire(job_id) is None
    # back to schedule with a new cron: next fire recomputed
    await env.world.jobs.update(dataclasses.replace(job, trigger=ScheduleTrigger("0 18 * * *")))
    await env.scheduler.refresh()
    assert env.scheduler.next_fire(job_id) == datetime(2026, 5, 1, 18, 0, tzinfo=UTC)


async def test_refresh_keeps_next_fire_of_unchanged_jobs() -> None:
    env, job_id = await make()
    before = env.scheduler.next_fire(job_id)
    env.world.clock.advance(minutes=2)
    await env.scheduler.refresh()
    assert env.scheduler.next_fire(job_id) == before


async def test_refresh_failure_keeps_the_previous_schedule() -> None:
    env, job_id = await make()

    async def broken() -> list[object]:
        raise RuntimeError("db down")

    env.world.jobs.list = broken  # type: ignore[method-assign,assignment]
    await env.scheduler.refresh()
    assert env.scheduler.next_fire(job_id) is not None


async def test_loop_fires_on_schedule_and_stops_gracefully() -> None:
    env, job_id = await make(refresh_interval=3600.0, max_sleep=60.0)
    env.scheduler.start()
    for _ in range(50):
        await asyncio.sleep(0)
        if len(await env.runs()) >= 2:
            break
    await env.scheduler.stop()
    runs = await env.runs()
    assert len(runs) >= 2 and all(r == (job_id, "schedule") for r in runs)
    # sleeps never exceed max_sleep and the loop is really stopped
    assert max(env.sleeps) <= 60.0
    count = len(env.sleeps)
    await asyncio.sleep(0.01)
    assert len(env.sleeps) == count


async def test_stop_cancels_inflight_runs_and_is_idempotent() -> None:
    env, _ = await make()
    block = asyncio.Event()

    async def hang(*args: object, **kwargs: object) -> None:
        started.set()
        await block.wait()

    started = asyncio.Event()
    env.world.runner.run = hang  # type: ignore[method-assign,assignment]
    env.world.clock.advance(minutes=5)
    await env.scheduler.tick()
    await started.wait()
    await env.scheduler.stop()
    await env.scheduler.stop()
    assert env.scheduler.running_jobs == frozenset()


async def test_start_twice_is_rejected() -> None:
    env, _ = await make()
    env.scheduler.start()
    with pytest.raises(RuntimeError):
        env.scheduler.start()
    await env.scheduler.stop()
