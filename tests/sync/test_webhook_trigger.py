import dataclasses

import pytest

from conector_odoo.application.event_bus import InMemoryEventBus
from conector_odoo.application.sync_trigger import TriggerSyncJob
from conector_odoo.application.webhook_triggers import (
    HandleWebhookTrigger,
    register_webhook_triggers,
)
from conector_odoo.domain.events import PARTNER_CREATED, PARTNER_UPDATED, OdooEvent
from conector_odoo.domain.sync import Direction, ScheduleTrigger, WebhookTrigger
from conector_odoo.domain.sync_runs import RunFilter
from tests.sync.harness import World, build_world

ON_CREATED = WebhookTrigger((PARTNER_CREATED,))


async def setup(world: World, **job: object) -> tuple[HandleWebhookTrigger, int]:
    for i in (1, 2, 3):
        world.odoo.seed("customers", {"name": f"Ana {i}", "email": f"ANA{i}@X.com"})
    created = await world.add_job(**job)
    assert created.id is not None
    return HandleWebhookTrigger(world.jobs, TriggerSyncJob(world.runner)), created.id


async def runs(world: World) -> list[tuple[str, int, dict[str, object]]]:
    found = await world.runs.list_runs(RunFilter(), 50)
    return [(r.trigger, r.counters.created, r.options) for r in found]


async def test_event_runs_matching_job_for_the_changed_record_only() -> None:
    world = build_world()
    handle, _ = await setup(world, trigger=ON_CREATED)
    await handle(OdooEvent(PARTNER_CREATED, "customers", 2))
    assert await runs(world) == [("webhook", 1, {"only": {"forward": ["2"]}})]
    assert [r.fields["full_name"] for r in world.rest.records["clients"].values()] == ["Ana 2"]


async def test_event_for_another_model_runs_the_full_job() -> None:
    world = build_world()
    handle, _ = await setup(world, trigger=ON_CREATED)
    await handle(OdooEvent(PARTNER_CREATED, "res.partner", 2))
    assert [(t, c) for t, c, _ in await runs(world)] == [("webhook", 3)]


async def test_b_to_a_job_always_runs_in_full() -> None:
    world = build_world()
    handle, _ = await setup(world, trigger=ON_CREATED, direction=Direction.B_TO_A)
    world.rest.seed("clients", {"full_name": "Bea", "email": "b@x.com"})
    await handle(OdooEvent(PARTNER_CREATED, "customers", 2))
    [(trigger, _, options)] = await runs(world)
    assert (trigger, options) == ("webhook", {})


@pytest.mark.parametrize(
    "overrides",
    [
        {"trigger": WebhookTrigger((PARTNER_UPDATED,))},  # other event type
        {"trigger": ScheduleTrigger("* * * * *")},  # not a webhook job
        {"enabled": False},
    ],
)
async def test_non_matching_jobs_do_not_run(overrides: dict[str, object]) -> None:
    world = build_world()
    handle, _ = await setup(world, **{"trigger": ON_CREATED, **overrides})
    await handle(OdooEvent(PARTNER_CREATED, "customers", 1))
    assert await runs(world) == []


async def test_busy_job_is_skipped_without_error() -> None:
    world = build_world()
    handle, job_id = await setup(world, trigger=ON_CREATED)
    from tests.sync.harness import T0

    await world.runs.create(
        job_id, "manual", dry_run=False, started_at=T0, stale_before=T0.replace(year=2020)
    )
    await handle(OdooEvent(PARTNER_CREATED, "customers", 1))  # must not raise
    assert [t for t, _, _ in await runs(world)] == ["manual"]


async def test_one_failing_job_does_not_block_the_others_and_signals_failure() -> None:
    world = build_world()
    handle, first = await setup(world, trigger=ON_CREATED)
    base = await world.jobs.get(first)
    assert base is not None
    other = await world.jobs.add(dataclasses.replace(base, id=None, name="second"))
    original = world.runner.run

    async def flaky(job_id: int, **kwargs: object):  # type: ignore[no-untyped-def]
        if job_id == first:
            raise RuntimeError("boom")
        return await original(job_id, **kwargs)  # type: ignore[arg-type]

    world.runner.run = flaky  # type: ignore[method-assign]
    with pytest.raises(ExceptionGroup):
        await handle(OdooEvent(PARTNER_CREATED, "res.partner", 1))
    assert [j.job_id for j in await world.runs.list_runs(RunFilter(), 5)] == [other.id]


async def test_registered_on_the_bus_it_reports_failures_to_the_publisher() -> None:
    world = build_world()
    handle, _ = await setup(world, trigger=ON_CREATED)
    bus = InMemoryEventBus()
    register_webhook_triggers(bus, handle)
    assert await bus.publish(OdooEvent(PARTNER_CREATED, "customers", 3)) is True
    assert len(await runs(world)) == 1
    assert await bus.publish(OdooEvent(PARTNER_UPDATED, "customers", 3)) is True
    assert len(await runs(world)) == 1  # no job listens to partner.updated
