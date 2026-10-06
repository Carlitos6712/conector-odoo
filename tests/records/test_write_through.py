"""Records use cases: the primary write is followed by a write-through to the counterpart."""

from typing import Any

import pytest

from conector_odoo.application.record_propagation import RecordPropagator
from conector_odoo.application.records import CreateRecord, DeleteRecord, UpdateRecord
from conector_odoo.domain.errors import RecordRejected, RemoteUnavailable, ResourceNotFound
from conector_odoo.domain.sync import Direction
from conector_odoo.domain.sync_runs import RunCounters, Side
from tests.sync.harness import World, build_world
from tests.sync.test_runner_bidirectional import synced_pair


def provider(world: World) -> Any:
    async def endpoint(profile_id: int) -> Any:
        return {1: world.odoo, 2: world.rest}[profile_id]

    return endpoint


def make(world: World) -> tuple[CreateRecord, UpdateRecord, DeleteRecord]:
    endpoints = provider(world)
    propagator = RecordPropagator(
        world.jobs, world.mappings, world.xrefs, endpoints, clock=world.clock
    )
    profiles: Any = None  # only ListRecords reads profiles
    return (
        CreateRecord(profiles, endpoints, propagator),
        UpdateRecord(profiles, endpoints, propagator),
        DeleteRecord(profiles, endpoints, world.xrefs, propagator),
    )


# -- update ---------------------------------------------------------------------------------


async def test_update_writes_the_primary_and_reaches_the_counterpart() -> None:
    world = build_world()
    job_id = await synced_pair(world)
    _, update, _ = make(world)
    result = await update.execute(1, "customers", "1", {"name": "Ana Z"})
    assert result.record.fields["name"] == "Ana Z"
    [outcome] = result.propagation
    assert (outcome.job_id, outcome.action, outcome.side) == (job_id, "updated", Side.SOURCE)
    assert world.rest.records["clients"]["1"].fields["full_name"] == "Ana Z"
    assert (await world.runner.run(job_id)).counters == RunCounters(skipped=2)


async def test_update_of_the_b_side_reaches_a() -> None:
    world = build_world()
    await synced_pair(world)
    _, update, _ = make(world)
    result = await update.execute(2, "clients", "1", {"full_name": "Bea"})
    assert [o.action for o in result.propagation] == ["updated"]
    assert world.odoo.records["customers"]["1"].fields["name"] == "Bea"


async def test_update_without_any_bidirectional_job_has_no_propagation() -> None:
    world = build_world()
    world.odoo.seed("customers", {"name": "Ana", "email": "a@x.com"})
    _, update, _ = make(world)
    result = await update.execute(1, "customers", "1", {"name": "Z"})
    assert result.propagation == ()


async def test_update_survives_a_failing_counterpart_and_reports_it() -> None:
    world = build_world()
    job_id = await synced_pair(world)
    world.rest.reject_next(RemoteUnavailable("suwe is down"))
    _, update, _ = make(world)
    result = await update.execute(1, "customers", "1", {"name": "Ana Z"})
    assert result.record.fields["name"] == "Ana Z"  # primary kept
    [outcome] = result.propagation
    assert outcome.action == "failed" and "suwe is down" in (outcome.warning or "")
    # the xref is stale, so the next run reconciles
    assert (await world.runner.run(job_id)).counters.updated == 1


async def test_update_validation_errors_do_not_propagate() -> None:
    world = build_world()
    await synced_pair(world)
    _, update, _ = make(world)
    with pytest.raises(RecordRejected):
        await update.execute(1, "customers", "1", {"nope": 1})
    assert world.rest.update_calls == 0


# -- create ---------------------------------------------------------------------------------


async def test_create_makes_the_primary_and_the_counterpart_and_links_them() -> None:
    world = build_world()
    job = await world.add_job(direction=Direction.BIDIRECTIONAL)
    assert job.id is not None
    create, _, _ = make(world)
    result = await create.execute(1, "customers", {"name": "Cleo", "email": "cleo@x.com"})
    assert result.record.id is not None
    [outcome] = result.propagation
    assert (outcome.action, outcome.side) == ("created", Side.SOURCE)
    assert [r.fields["full_name"] for r in world.rest.records["clients"].values()] == ["Cleo"]
    assert (await world.runner.run(job.id)).counters == RunCounters(skipped=2)
    assert world.odoo.create_calls == 1 and world.rest.create_calls == 1


async def test_create_on_the_b_side_creates_in_a() -> None:
    world = build_world()
    await world.add_job(direction=Direction.BIDIRECTIONAL)
    create, _, _ = make(world)
    result = await create.execute(2, "clients", {"full_name": "Dan", "email": "dan@x.com"})
    assert [o.action for o in result.propagation] == ["created"]
    assert [r.fields["name"] for r in world.odoo.records["customers"].values()] == ["Dan"]


async def test_create_keeps_the_primary_when_the_counterpart_fails() -> None:
    world = build_world()
    await world.add_job(direction=Direction.BIDIRECTIONAL)
    world.rest.reject_next(RecordRejected("email invalid"))
    create, _, _ = make(world)
    result = await create.execute(1, "customers", {"name": "Cleo", "email": "cleo@x.com"})
    assert len(world.odoo.records["customers"]) == 1
    [outcome] = result.propagation
    assert outcome.action == "failed" and "email invalid" in (outcome.warning or "")
    assert world.rest.records["clients"] == {}


async def test_create_rejects_unknown_readonly_and_empty_fields() -> None:
    world = build_world()
    create, _, _ = make(world)
    for fields in ({"nope": 1}, {}):
        with pytest.raises(RecordRejected):
            await create.execute(1, "customers", fields)
    assert world.odoo.create_calls == 0


async def test_create_on_an_unknown_resource_is_not_found() -> None:
    world = build_world()
    create, _, _ = make(world)
    with pytest.raises(ResourceNotFound):
        await create.execute(1, "nope", {"name": "x"})


# -- delete ---------------------------------------------------------------------------------


async def test_delete_removes_the_counterpart_and_the_xref() -> None:
    world = build_world()
    job_id = await synced_pair(world)
    _, _, delete = make(world)
    result = await delete.execute(1, "customers", "1")
    outcomes = result.propagation
    assert not result.already_deleted
    assert [(o.action, o.side) for o in outcomes] == [("deleted", Side.SOURCE)]
    assert world.odoo.records["customers"] == {} and world.rest.records["clients"] == {}
    assert await world.xrefs.list(job_id) == []


async def test_delete_on_the_b_side_removes_the_a_record() -> None:
    world = build_world()
    job_id = await synced_pair(world)
    _, _, delete = make(world)
    outcomes = (await delete.execute(2, "clients", "1")).propagation
    assert [o.action for o in outcomes] == ["deleted"]
    assert world.odoo.records["customers"] == {}
    assert await world.xrefs.list(job_id) == []


async def test_delete_with_a_counterpart_already_gone_is_a_success() -> None:
    world = build_world()
    job_id = await synced_pair(world)
    await world.rest.delete("clients", "1")
    _, _, delete = make(world)
    [outcome] = (await delete.execute(1, "customers", "1")).propagation
    assert outcome.action == "deleted" and outcome.warning is None
    assert await world.xrefs.list(job_id) == []


async def test_delete_refused_by_the_counterpart_keeps_the_primary_gone_and_the_xref() -> None:
    world = build_world()
    job_id = await synced_pair(world)
    _, _, delete = make(world)

    async def refuse(resource: str, id: str) -> None:
        raise RecordRejected("still referenced")

    world.rest.delete = refuse  # type: ignore[method-assign]
    [outcome] = (await delete.execute(1, "customers", "1")).propagation
    assert outcome.action == "failed" and "still referenced" in (outcome.warning or "")
    assert world.odoo.records["customers"] == {}  # the primary delete is not rolled back
    assert len(await world.xrefs.list(job_id)) == 1  # the pair stays linked


async def test_delete_of_a_target_record_of_a_one_way_job_still_forgets_its_xref() -> None:
    world = build_world()
    world.odoo.seed("customers", {"name": "Ana", "email": "a@x.com"})
    job = await world.add_job()  # a_to_b
    assert job.id is not None
    await world.runner.run(job.id)
    _, _, delete = make(world)
    result = await delete.execute(2, "clients", "1")
    assert result.propagation == () and not result.already_deleted
    assert await world.xrefs.list(job.id) == []


async def test_delete_of_a_missing_primary_is_an_idempotent_success() -> None:
    world = build_world()
    await synced_pair(world)
    _, _, delete = make(world)
    result = await delete.execute(1, "customers", "99")
    assert result.propagation == () and result.already_deleted
    assert world.rest.delete_calls == 0  # nothing to mirror


async def test_delete_of_an_already_gone_primary_still_forgets_its_stale_xrefs() -> None:
    world = build_world()
    job_id = await synced_pair(world)
    await world.odoo.delete("customers", "1")  # gone behind the connector's back
    assert await world.xrefs.list(job_id) != []
    _, _, delete = make(world)
    result = await delete.execute(1, "customers", "1")
    assert result.propagation == () and result.already_deleted
    assert await world.xrefs.list(job_id) == []
    assert world.rest.delete_calls == 0


async def test_delete_on_an_unknown_resource_is_still_not_found() -> None:
    world = build_world()
    await synced_pair(world)
    _, _, delete = make(world)
    with pytest.raises(ResourceNotFound):
        await delete.execute(1, "nope", "1")
