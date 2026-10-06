import pytest

from conector_odoo.domain.errors import RecordRejected
from conector_odoo.domain.records import RecordFilter
from conector_odoo.domain.sync import ConflictRule, Direction
from conector_odoo.domain.sync_runs import ErrorKind, RunCounters, RunStatus, Side
from tests.sync.harness import World, build_world

BIDI = Direction.BIDIRECTIONAL


async def synced_pair(world: World, **job: object) -> int:
    """One customer on each side, already synced and in sync. Returns the job id."""
    world.odoo.seed(
        "customers", {"name": "Ana", "email": "ana@x.com", "write_date": "2026-05-01 10:00:00"}
    )
    created = await world.add_job(direction=BIDI, **job)
    assert created.id is not None
    first = await world.runner.run(created.id)
    assert first.counters.created == 1
    return created.id


async def edit_both(world: World, a_time: str, b_time: str) -> None:
    await world.odoo.update("customers", "1", {"name": "Ana (odoo)", "write_date": a_time})
    await world.rest.update("clients", "1", {"full_name": "Ana (rest)", "updated": b_time})


def names(world: World) -> tuple[object, object]:
    return (
        world.odoo.records["customers"]["1"].get("name"),
        world.rest.records["clients"]["1"].get("full_name"),
    )


async def test_first_bidirectional_run_does_not_echo_written_records_back() -> None:
    world = build_world()
    world.odoo.seed("customers", {"name": "Ana", "email": "ANA@x.com"})
    world.odoo.seed("customers", {"name": "Bea", "email": "bea@x.com"})
    job = await world.add_job(direction=BIDI)
    assert job.id is not None
    run = await world.runner.run(job.id)
    assert run.counters == RunCounters(created=2, skipped=2)  # reverse pass skips the echoes
    assert (world.odoo.create_calls, world.odoo.update_calls) == (0, 0)
    assert len(world.odoo.records["customers"]) == 2
    xref = (await world.xrefs.list(job.id))[0]
    assert xref.content_hash and xref.reverse_hash
    again = await world.runner.run(job.id)
    assert again.counters == RunCounters(skipped=4)


async def test_record_created_on_the_target_side_is_created_in_the_source_once() -> None:
    world = build_world()
    job = await world.add_job(direction=BIDI)
    assert job.id is not None
    world.rest.seed("clients", {"full_name": "Cleo", "email": "cleo@x.com"})
    run = await world.runner.run(job.id)
    assert run.counters == RunCounters(created=1)
    assert [r.fields for r in world.odoo.records["customers"].values()] == [
        {"name": "Cleo", "email": "cleo@x.com"}
    ]
    xref = await world.xrefs.get_source(job.id, "customers", "1")
    assert xref is not None and (xref.source_id, xref.target_id) == ("1", "1")
    again = await world.runner.run(job.id)
    assert again.counters == RunCounters(skipped=2)  # no ping-pong
    assert world.rest.update_calls == 0 and world.odoo.update_calls == 0


async def test_one_sided_edits_flow_in_the_right_direction_without_conflict() -> None:
    world = build_world()
    job_id = await synced_pair(world)
    await world.odoo.update("customers", "1", {"name": "Ana A"})
    run = await world.runner.run(job_id)
    assert run.counters == RunCounters(updated=1, skipped=1)
    assert names(world) == ("Ana A", "Ana A")

    await world.rest.update("clients", "1", {"full_name": "Ana B"})
    run = await world.runner.run(job_id)
    assert run.counters == RunCounters(updated=1, skipped=1)
    assert names(world) == ("Ana B", "Ana B")
    assert run.counters.conflicts == 0


async def test_conflict_source_wins() -> None:
    world = build_world()
    job_id = await synced_pair(world, conflict_rule=ConflictRule.SOURCE_WINS)
    await edit_both(world, "2026-05-02 10:00:00", "2026-05-03T10:00:00")
    run = await world.runner.run(job_id)
    assert run.counters.conflicts == 1 and run.counters.failed == 0
    assert run.status is RunStatus.SUCCEEDED
    assert names(world) == ("Ana (odoo)", "Ana (odoo)")
    assert (await world.runner.run(job_id)).counters == RunCounters(skipped=2)  # settled


async def test_conflict_target_wins() -> None:
    world = build_world()
    job_id = await synced_pair(world, conflict_rule=ConflictRule.TARGET_WINS)
    await edit_both(world, "2026-05-02 10:00:00", "2026-05-03T10:00:00")
    run = await world.runner.run(job_id)
    assert run.counters.conflicts == 1
    assert names(world) == ("Ana (rest)", "Ana (rest)")
    assert (await world.runner.run(job_id)).counters == RunCounters(skipped=2)


@pytest.mark.parametrize(
    ("a_time", "b_time", "expected"),
    [
        ("2026-05-04 10:00:00", "2026-05-03T10:00:00", "Ana (odoo)"),
        ("2026-05-02 10:00:00", "2026-05-03T10:00:00Z", "Ana (rest)"),
        ("2026-05-03 12:00:00", "2026-05-03T10:00:00+02:00", "Ana (odoo)"),  # tz aware
    ],
)
async def test_conflict_newest_wins(a_time: str, b_time: str, expected: str) -> None:
    world = build_world()
    job_id = await synced_pair(
        world,
        conflict_rule=ConflictRule.NEWEST_WINS,
        source_updated_field="write_date",
        target_updated_field="updated",
    )
    await edit_both(world, a_time, b_time)
    run = await world.runner.run(job_id)
    assert run.counters.conflicts == 1 and run.status is RunStatus.SUCCEEDED
    assert names(world) == (expected, expected)


async def test_newest_wins_without_comparable_timestamps_flags_the_conflict() -> None:
    world = build_world()
    job_id = await synced_pair(
        world,
        conflict_rule=ConflictRule.NEWEST_WINS,
        source_updated_field="write_date",
        target_updated_field="updated",
    )
    await world.odoo.update("customers", "1", {"name": "Ana (odoo)"})
    await world.rest.update("clients", "1", {"full_name": "Ana (rest)"})  # no 'updated' at all
    run = await world.runner.run(job_id)
    assert run.counters.conflicts == 1
    assert names(world) == ("Ana (odoo)", "Ana (rest)")  # nothing written


async def test_flag_conflict_writes_nothing_and_records_a_non_retryable_conflict_error() -> None:
    world = build_world()
    job_id = await synced_pair(world, conflict_rule=ConflictRule.FLAG_CONFLICT)
    writes = (world.odoo.update_calls, world.rest.update_calls)
    await edit_both(world, "2026-05-02 10:00:00", "2026-05-03T10:00:00")
    writes_after_edit = (world.odoo.update_calls + 0, world.rest.update_calls + 0)

    run = await world.runner.run(job_id)

    assert (world.odoo.update_calls, world.rest.update_calls) == writes_after_edit
    assert writes_after_edit != writes  # (the edits themselves were the only writes)
    assert names(world) == ("Ana (odoo)", "Ana (rest)")
    assert run.counters.conflicts == 1 and run.counters.failed == 0
    assert run.status is RunStatus.PARTIAL
    [error] = await world.runs.list_errors(run.id)
    assert (error.kind, error.retryable, error.side, error.record_ref) == (
        ErrorKind.CONFLICT,
        False,
        Side.SOURCE,
        "1",
    )
    assert "conflict" in error.message
    flagged_again = await world.runner.run(job_id)  # still unresolved: reported again, once
    assert flagged_again.counters.conflicts == 1
    assert await world.runs.count_errors(flagged_again.id) == 1


async def test_conflicts_are_not_retried() -> None:
    from conector_odoo.domain.errors import RunNotResumable

    world = build_world()
    job_id = await synced_pair(world, conflict_rule=ConflictRule.FLAG_CONFLICT)
    await edit_both(world, "2026-05-02 10:00:00", "2026-05-03T10:00:00")
    run = await world.runner.run(job_id)
    with pytest.raises(RunNotResumable):
        await world.runner.retry_failed(run.id)


async def test_b_to_a_job_runs_only_the_reverse_pass_and_adopts_by_key() -> None:
    world = build_world()
    world.rest.seed("clients", {"full_name": "Bob", "email": "bob@x.com"})
    world.rest.seed("clients", {"full_name": "Cy", "email": "cy@x.com"})
    existing = world.odoo.seed("customers", {"name": "Old", "email": "bob@x.com"})
    job = await world.add_job(direction=Direction.B_TO_A, upsert_key="field:email")
    assert job.id is not None
    run = await world.runner.run(job.id)
    assert run.counters == RunCounters(created=1, updated=1)
    assert world.odoo.records["customers"][existing.id or ""].get("name") == "Bob"
    assert world.rest.create_calls == 0 and world.rest.update_calls == 0
    xref = await world.xrefs.get_source(job.id, "customers", "1")
    assert xref is not None and xref.source_id == existing.id and xref.target_id == "1"
    assert (await world.runner.run(job.id)).counters == RunCounters(skipped=2)


async def test_dry_run_of_a_bidirectional_job_writes_nothing() -> None:
    world = build_world()
    world.odoo.seed("customers", {"name": "Ana", "email": "ana@x.com"})
    world.rest.seed("clients", {"full_name": "Zed", "email": "zed@x.com"})
    job = await world.add_job(direction=BIDI)
    assert job.id is not None
    run = await world.runner.run(job.id, dry_run=True)
    assert run.counters == RunCounters(created=2)  # Ana -> rest, Zed -> odoo
    assert (world.odoo.create_calls, world.rest.create_calls) == (0, 0)
    assert await world.xrefs.list(job.id) == []
    assert [s["action"] for s in run.sample] == ["create", "create"]


async def test_failed_reverse_record_is_retried_through_the_reverse_pass() -> None:
    world = build_world()
    world.rest.seed("clients", {"full_name": "Cy", "email": "cy@x.com"})
    flag = {"on": True}
    world.odoo.reject_when(lambda op, res, f: RecordRejected("no") if flag["on"] else None)
    job = await world.add_job(direction=BIDI)
    assert job.id is not None
    first = await world.runner.run(job.id)
    assert first.counters == RunCounters(failed=1)
    [error] = await world.runs.list_errors(first.id)
    assert (error.side, error.record_ref) == (Side.TARGET, "1")
    flag["on"] = False
    retry = await world.runner.retry_failed(first.id)
    assert retry.counters == RunCounters(created=1) and retry.status is RunStatus.SUCCEEDED
    assert len(world.odoo.records["customers"]) == 1
    [done] = await world.runs.list_errors(first.id)
    assert done.retried is True


async def test_checkpoint_tracks_the_max_updated_at_of_the_source() -> None:
    world = build_world()
    world.odoo.seed(
        "customers", {"name": "A", "email": "a@x.com", "write_date": "2026-05-01 10:00:00"}
    )
    world.odoo.seed(
        "customers", {"name": "B", "email": "b@x.com", "write_date": "2026-05-03 09:00:00"}
    )
    world.odoo.seed(
        "customers", {"name": "C", "email": "c@x.com", "write_date": "2026-05-02 09:00:00"}
    )
    job = await world.add_job(
        source_updated_field="write_date", target_updated_field="updated", batch_size=2
    )
    assert job.id is not None
    run = await world.runner.run(job.id)
    assert run.checkpoint["max_updated_at"] == "2026-05-03T09:00:00+00:00"


async def test_resume_after_a_crash_in_the_reverse_pass_does_not_replay_the_forward_pass() -> None:
    class Crash(BaseException):
        pass

    world = build_world()
    world.odoo.seed("customers", {"name": "Ana", "email": "ana@x.com"})
    world.rest.seed("clients", {"full_name": "Cy", "email": "cy@x.com"})
    armed = {"on": True}
    world.odoo.reject_when(lambda op, res, f: Crash() if armed["on"] else None)
    job = await world.add_job(direction=BIDI)
    assert job.id is not None
    with pytest.raises(Crash):
        await world.runner.run(job.id)
    crashed = await world.last_run()
    assert crashed.checkpoint["pass"] == "forward" and crashed.checkpoint["done"] is True
    armed["on"] = False
    world.clock.advance(minutes=30)
    run = await world.runner.resume(crashed.id)
    assert run.status is RunStatus.SUCCEEDED
    assert run.counters.created == 2  # Ana forward (before the crash) + Cy reverse
    assert len(world.rest.records["clients"]) == 2 and len(world.odoo.records["customers"]) == 2


async def test_reverse_record_filter_limits_what_the_reverse_pass_creates() -> None:
    world = build_world()
    world.rest.seed("clients", {"full_name": "Cleo", "email": "cleo@x.com"})
    world.rest.seed("clients", {"full_name": "Dan", "email": "dan@x.com"})
    job = await world.add_job(
        direction=BIDI, reverse_record_filter=RecordFilter(equals={"full_name": "Cleo"})
    )
    assert job.id is not None
    run = await world.runner.run(job.id)
    assert run.counters == RunCounters(created=1)
    assert [r.fields["name"] for r in world.odoo.records["customers"].values()] == ["Cleo"]
    assert await world.xrefs.get_source(job.id, "customers", "2") is None  # Dan never reached


async def test_empty_reverse_record_filter_keeps_creating_every_target_record() -> None:
    world = build_world()
    world.rest.seed("clients", {"full_name": "Cleo", "email": "cleo@x.com"})
    world.rest.seed("clients", {"full_name": "Dan", "email": "dan@x.com"})
    job = await world.add_job(direction=BIDI)
    assert job.id is not None
    run = await world.runner.run(job.id)
    assert run.counters == RunCounters(created=2)


async def test_forward_and_reverse_filters_apply_to_their_own_pass_only() -> None:
    world = build_world()
    world.odoo.seed("customers", {"name": "Ana", "email": "ana@x.com"})
    world.odoo.seed("customers", {"name": "Bea", "email": "bea@x.com"})
    world.rest.seed("clients", {"full_name": "Cleo", "email": "cleo@x.com"})
    world.rest.seed("clients", {"full_name": "Dan", "email": "dan@x.com"})
    job = await world.add_job(
        direction=BIDI,
        record_filter=RecordFilter(equals={"name": "Ana"}),
        reverse_record_filter=RecordFilter(equals={"full_name": "Dan"}),
    )
    assert job.id is not None
    await world.runner.run(job.id)
    assert sorted(r.fields["name"] for r in world.odoo.records["customers"].values()) == [
        "Ana",
        "Bea",
        "Dan",
    ]
    assert sorted(r.fields["full_name"] for r in world.rest.records["clients"].values()) == [
        "Ana",
        "Cleo",
        "Dan",
    ]
