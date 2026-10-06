"""Forgetting the cross-references of a target record that was deleted outside a sync run."""

from conector_odoo.domain.sync_runs import RunCounters
from tests.sync.harness import World, build_world


async def _synced(n: int = 3) -> tuple[World, int]:
    world = build_world()
    for i in range(1, n + 1):
        world.odoo.seed("customers", {"name": f"Ana {i}", "email": f"ana{i}@x.com"})
    job = await world.add_job()
    assert job.id is not None
    await world.runner.run(job.id)
    return world, job.id


async def test_forget_target_removes_only_the_xrefs_pointing_to_that_record() -> None:
    world, job_id = await _synced()
    removed = await world.xrefs.forget_target(2, "clients", "2")
    assert removed == 1
    assert [x.target_id for x in await world.xrefs.list(job_id)] == ["1", "3"]


async def test_forget_target_is_scoped_by_profile_and_resource() -> None:
    world, job_id = await _synced()
    assert await world.xrefs.forget_target(1, "clients", "2") == 0  # other profile
    assert await world.xrefs.forget_target(2, "customers", "2") == 0  # other resource
    assert await world.xrefs.forget_target(2, "clients", "999") == 0  # unknown id
    assert len(await world.xrefs.list(job_id)) == 3


async def test_stale_xref_hides_a_deleted_target_but_forgetting_it_recreates_it() -> None:
    world, job_id = await _synced()
    await world.rest.delete("clients", "2")  # removed through the records API
    stale = await world.runner.run(job_id)
    assert stale.counters == RunCounters(skipped=3)  # the stale xref makes the run skip it
    assert "2" not in world.rest.records["clients"]

    await world.xrefs.forget_target(2, "clients", "2")
    healed = await world.runner.run(job_id)
    assert healed.counters == RunCounters(created=1, skipped=2)
    assert [r.fields["full_name"] for r in world.rest.records["clients"].values()] == [
        "Ana 1",
        "Ana 3",
        "Ana 2",
    ]
