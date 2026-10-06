"""Write-through of one record edit to its counterpart, through the sync xref."""

from typing import Any

import pytest

from conector_odoo.application.record_propagation import RecordPropagator
from conector_odoo.domain.errors import RecordRejected, RemoteUnavailable
from conector_odoo.domain.records import Record
from conector_odoo.domain.sync import Direction
from conector_odoo.domain.sync_runs import RunCounters, Side
from tests.sync.harness import World, build_world
from tests.sync.test_runner_bidirectional import BIDI, synced_pair


def propagator(world: World) -> RecordPropagator:
    async def endpoint(profile_id: int) -> Any:
        return {1: world.odoo, 2: world.rest}[profile_id]

    return RecordPropagator(world.jobs, world.mappings, world.xrefs, endpoint, clock=world.clock)


async def assert_in_sync(world: World, job_id: int, *, skipped: int) -> None:
    """A following full run finds nothing to do: both hashes in the xref are current."""
    assert (await world.runner.run(job_id)).counters == RunCounters(skipped=skipped)


async def edit_a(world: World, **fields: Any) -> Record:
    return await world.odoo.update("customers", "1", fields)


async def edit_b(world: World, **fields: Any) -> Record:
    return await world.rest.update("clients", "1", fields)


# -- update ---------------------------------------------------------------------------------


async def test_update_on_side_a_reaches_b_and_a_run_has_nothing_to_do() -> None:
    world = build_world()
    job_id = await synced_pair(world)
    written = await edit_a(world, name="Ana Z", email="ANA.Z@x.com")
    [outcome] = await propagator(world).propagate_update(1, "customers", "1", written)
    assert (outcome.job_id, outcome.action, outcome.side, outcome.warning) == (
        job_id,
        "updated",
        Side.SOURCE,
        None,
    )
    assert world.rest.records["clients"]["1"].fields["full_name"] == "Ana Z"
    assert world.rest.records["clients"]["1"].fields["email"] == "ana.z@x.com"
    await assert_in_sync(world, job_id, skipped=2)
    assert world.odoo.update_calls == 1  # only the user's edit: nothing echoed back


async def test_update_on_side_b_reaches_a_through_the_reverse_mapping() -> None:
    world = build_world()
    job_id = await synced_pair(world)
    written = await edit_b(world, full_name="Bea")
    [outcome] = await propagator(world).propagate_update(2, "clients", "1", written)
    assert (outcome.action, outcome.side) == ("updated", Side.TARGET)
    assert world.odoo.records["customers"]["1"].fields["name"] == "Bea"
    await assert_in_sync(world, job_id, skipped=2)
    assert world.rest.update_calls == 1


async def test_update_with_nothing_to_change_is_skipped_without_a_write() -> None:
    world = build_world()
    await synced_pair(world)
    written = world.odoo.records["customers"]["1"]  # unchanged
    [outcome] = await propagator(world).propagate_update(1, "customers", "1", written)
    assert outcome.action == "skipped" and outcome.warning is None
    assert world.rest.update_calls == 0


async def test_update_recreates_a_counterpart_that_was_deleted() -> None:
    world = build_world()
    job_id = await synced_pair(world)
    await world.rest.delete("clients", "1")
    written = await edit_a(world, name="Ana Z")
    [outcome] = await propagator(world).propagate_update(1, "customers", "1", written)
    assert outcome.action == "created"
    [client] = world.rest.records["clients"].values()
    assert client.fields["full_name"] == "Ana Z"
    xref = (await world.xrefs.list(job_id))[0]
    assert xref.target_id == client.id
    await assert_in_sync(world, job_id, skipped=2)


async def test_update_of_a_record_without_xref_is_skipped() -> None:
    world = build_world()
    await synced_pair(world)
    loose = world.odoo.seed("customers", {"name": "Loose", "email": "l@x.com"})
    [outcome] = await propagator(world).propagate_update(1, "customers", loose.id or "", loose)
    assert outcome.action == "skipped"
    assert len(world.rest.records["clients"]) == 1


async def test_counterpart_rejection_is_a_warning_and_keeps_the_xref_stale() -> None:
    world = build_world()
    job_id = await synced_pair(world)
    before = (await world.xrefs.list(job_id))[0]
    written = await edit_a(world, name="Ana Z")
    world.rest.reject_next(RecordRejected("name too long"))
    [outcome] = await propagator(world).propagate_update(1, "customers", "1", written)
    assert outcome.action == "failed" and "name too long" in (outcome.warning or "")
    assert (await world.xrefs.list(job_id))[0] == before
    run = await world.runner.run(job_id)  # the next run reconciles
    assert run.counters.updated == 1
    assert world.rest.records["clients"]["1"].fields["full_name"] == "Ana Z"


async def test_counterpart_failure_never_raises() -> None:
    world = build_world()
    await synced_pair(world)
    written = await edit_a(world, name="Ana Z")
    world.rest.reject_next(RemoteUnavailable("down"))
    [outcome] = await propagator(world).propagate_update(1, "customers", "1", written)
    assert outcome.action == "failed" and outcome.warning


async def test_a_mapping_error_is_reported_not_raised() -> None:
    world = build_world()
    await synced_pair(world)
    written = Record("1", {"name": "Ana Z"})  # the required email is missing
    [outcome] = await propagator(world).propagate_update(1, "customers", "1", written)
    assert outcome.action == "failed" and "email" in (outcome.warning or "")


# -- delete ---------------------------------------------------------------------------------


@pytest.mark.parametrize(("profile", "resource"), [(1, "customers"), (2, "clients")])
async def test_delete_removes_the_counterpart_and_drops_the_xref(
    profile: int, resource: str
) -> None:
    world = build_world()
    job_id = await synced_pair(world)
    [outcome] = await propagator(world).propagate_delete(profile, resource, "1")
    assert outcome.action == "deleted" and outcome.warning is None
    counterpart = world.rest if profile == 1 else world.odoo
    assert all(not table for table in counterpart.records.values())
    assert await world.xrefs.list(job_id) == []


async def test_delete_when_the_counterpart_is_already_gone_is_a_success() -> None:
    world = build_world()
    job_id = await synced_pair(world)
    await world.rest.delete("clients", "1")
    [outcome] = await propagator(world).propagate_delete(1, "customers", "1")
    assert outcome.action == "deleted" and outcome.warning is None
    assert await world.xrefs.list(job_id) == []


async def test_delete_refused_by_the_counterpart_keeps_the_xref_and_warns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = build_world()
    job_id = await synced_pair(world)

    async def refuse(resource: str, record_id: str) -> None:
        raise RecordRejected("still referenced")

    monkeypatch.setattr(world.rest, "delete", refuse)
    [outcome] = await propagator(world).propagate_delete(1, "customers", "1")
    assert outcome.action == "failed" and "still referenced" in (outcome.warning or "")
    assert len(await world.xrefs.list(job_id)) == 1
    assert len(world.rest.records["clients"]) == 1


async def test_delete_of_a_record_without_xref_is_skipped() -> None:
    world = build_world()
    await synced_pair(world)
    [outcome] = await propagator(world).propagate_delete(1, "customers", "999")
    assert outcome.action == "skipped"
    assert len(world.rest.records["clients"]) == 1


# -- create ---------------------------------------------------------------------------------


async def test_create_on_side_a_creates_the_counterpart_and_links_it() -> None:
    world = build_world()
    job_id = await synced_pair(world)
    new = world.odoo.seed("customers", {"name": "Cy", "email": "CY@x.com"})
    [outcome] = await propagator(world).propagate_create(1, "customers", new)
    assert outcome.action == "created"
    created = [r for r in world.rest.records["clients"].values() if r.id != "1"]
    assert [r.fields for r in created] == [{"full_name": "Cy", "email": "cy@x.com"}]
    await assert_in_sync(world, job_id, skipped=4)


async def test_create_on_side_b_creates_in_a_through_the_reverse_mapping() -> None:
    world = build_world()
    job_id = await synced_pair(world)
    new = world.rest.seed("clients", {"full_name": "Dee", "email": "dee@x.com"})
    [outcome] = await propagator(world).propagate_create(2, "clients", new)
    assert (outcome.action, outcome.side) == ("created", Side.TARGET)
    assert any(r.fields["name"] == "Dee" for r in world.odoo.records["customers"].values())
    await assert_in_sync(world, job_id, skipped=4)


async def test_create_adopts_a_counterpart_with_the_same_key_field() -> None:
    world = build_world()
    job_id = await synced_pair(world, upsert_key="field:email")
    twin = world.rest.seed("clients", {"full_name": "Old Cy", "email": "cy@x.com"})
    new = world.odoo.seed("customers", {"name": "Cy", "email": "cy@x.com"})
    [outcome] = await propagator(world).propagate_create(1, "customers", new)
    assert outcome.action == "updated"
    assert world.rest.create_calls == 1  # only the initial sync created
    assert world.rest.records["clients"][twin.id or ""].fields["full_name"] == "Cy"
    await assert_in_sync(world, job_id, skipped=4)


async def test_create_of_an_already_linked_record_behaves_like_an_update() -> None:
    world = build_world()
    job_id = await synced_pair(world)
    written = await edit_a(world, name="Ana Z")
    [outcome] = await propagator(world).propagate_create(1, "customers", written)
    assert outcome.action == "updated"
    assert world.rest.create_calls == 1
    await assert_in_sync(world, job_id, skipped=2)


# -- which jobs take part ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"direction": Direction.A_TO_B},
        {"direction": Direction.B_TO_A},
        {"enabled": False},
    ],
)
async def test_jobs_that_are_not_enabled_bidirectional_are_ignored(
    overrides: dict[str, Any],
) -> None:
    world = build_world()
    world.odoo.seed("customers", {"name": "Ana", "email": "ana@x.com"})
    job = await world.add_job(direction=BIDI)
    assert job.id is not None
    await world.runner.run(job.id)
    from dataclasses import replace

    await world.jobs.update(replace(job, **overrides))
    written = await edit_a(world, name="Ana Z")
    assert await propagator(world).propagate_update(1, "customers", "1", written) == []
    assert await propagator(world).propagate_delete(1, "customers", "1") == []
    assert await propagator(world).propagate_create(1, "customers", written) == []
    assert world.rest.records["clients"]["1"].fields["full_name"] == "Ana"


async def test_every_matching_job_is_applied_and_reported() -> None:
    world = build_world()
    first = await synced_pair(world)
    second = await world.add_job(name="second", direction=BIDI)
    assert second.id is not None
    await world.runner.run(second.id)  # pairs the same records again through job 2
    written = await edit_a(world, name="Ana Z")
    outcomes = await propagator(world).propagate_update(1, "customers", "1", written)
    assert sorted((o.job_id, o.action) for o in outcomes) == [
        (first, "updated"),
        (second.id, "updated"),
    ]
