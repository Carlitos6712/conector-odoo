import dataclasses

import pytest

from conector_odoo.domain.errors import (
    JobAlreadyRunning,
    RecordRejected,
    RemoteAuthError,
    RemoteUnavailable,
    SyncJobNotFound,
)
from conector_odoo.domain.sync import TriggerKind
from conector_odoo.domain.sync_runs import ErrorKind, RunCounters, RunStatus, Side
from tests.sync.harness import World, build_world


def seed(world: World, n: int = 3) -> None:
    for i in range(1, n + 1):
        world.odoo.seed("customers", {"name": f"Ana {i}", "email": f"ANA{i}@X.com"})


async def test_creates_missing_records_and_records_xrefs() -> None:
    world = build_world()
    seed(world)
    job = await world.add_job()
    assert job.id is not None
    run = await world.runner.run(job.id, trigger=TriggerKind.MANUAL)
    assert (run.status, run.trigger, run.dry_run) == (RunStatus.SUCCEEDED, "manual", False)
    assert run.counters == RunCounters(created=3)
    assert run.finished_at is not None and run.duration_seconds == 0.0
    created = [r.fields for r in world.rest.records["clients"].values()]
    assert created == [{"full_name": f"Ana {i}", "email": f"ana{i}@x.com"} for i in (1, 2, 3)]
    refs = await world.xrefs.list(job.id)
    assert [(x.source_id, x.target_id) for x in refs] == [("1", "1"), ("2", "2"), ("3", "3")]
    assert all(x.content_hash and x.reverse_hash is None for x in refs)


async def test_create_uses_idempotency_key_with_job_source_and_hash() -> None:
    world = build_world()
    seed(world, 1)
    job = await world.add_job()
    assert job.id is not None
    await world.runner.run(job.id)
    ref = (await world.xrefs.list(job.id))[0]
    [(resource, key)] = world.rest._replays
    assert resource == "clients"
    assert key == f"sync:{job.id}:1:{ref.content_hash}"


async def test_rerun_without_changes_skips_everything() -> None:
    world = build_world()
    seed(world)
    job = await world.add_job()
    assert job.id is not None
    await world.runner.run(job.id)
    creates, updates = world.rest.create_calls, world.rest.update_calls
    again = await world.runner.run(job.id)
    assert again.counters == RunCounters(skipped=3)
    assert again.status is RunStatus.SUCCEEDED
    assert (world.rest.create_calls, world.rest.update_calls) == (creates, updates)


async def test_changed_source_record_is_updated_the_rest_skipped() -> None:
    world = build_world()
    seed(world)
    job = await world.add_job()
    assert job.id is not None
    await world.runner.run(job.id)
    await world.odoo.update("customers", "2", {"name": "Bea"})
    run = await world.runner.run(job.id)
    assert run.counters == RunCounters(updated=1, skipped=2)
    assert world.rest.records["clients"]["2"].get("full_name") == "Bea"
    assert world.rest.create_calls == 3


async def test_field_upsert_key_adopts_an_existing_target_record() -> None:
    world = build_world()
    seed(world, 2)
    existing = world.rest.seed("clients", {"full_name": "old", "email": "ana1@x.com"})
    job = await world.add_job(upsert_key="field:email")
    assert job.id is not None
    run = await world.runner.run(job.id)
    assert run.counters == RunCounters(created=1, updated=1)
    assert world.rest.records["clients"][existing.id or ""].get("full_name") == "Ana 1"
    xref = await world.xrefs.get_target(job.id, "customers", "1")
    assert xref is not None and xref.target_id == existing.id
    assert (await world.runner.run(job.id)).counters == RunCounters(skipped=2)


async def test_mapping_error_fails_only_that_record() -> None:
    world = build_world()
    seed(world, 1)
    world.odoo.seed("customers", {"name": "No mail"})  # required email missing
    seed(world, 1)
    job = await world.add_job()
    assert job.id is not None
    run = await world.runner.run(job.id)
    assert run.counters == RunCounters(created=2, failed=1)
    assert run.status is RunStatus.PARTIAL
    [error] = await world.runs.list_errors(run.id)
    assert (error.record_ref, error.kind, error.side) == ("2", ErrorKind.MAPPING, Side.SOURCE)
    assert "email" in error.message and error.retryable is False


async def test_rejected_record_is_isolated_and_batch_continues() -> None:
    world = build_world()
    seed(world, 4)
    world.rest.reject_when(
        lambda op, res, f: (
            RecordRejected("bad email", {"email": "invalid"})
            if f.get("email") == "ana2@x.com"
            else None
        )
    )
    job = await world.add_job(batch_size=10)
    assert job.id is not None
    run = await world.runner.run(job.id)
    assert run.counters == RunCounters(created=3, failed=1)
    [error] = await world.runs.list_errors(run.id)
    assert (error.record_ref, error.kind, error.retryable) == ("2", ErrorKind.REJECTED, False)
    assert error.payload is not None and error.payload["field_errors"] == {"email": "invalid"}


async def test_unavailable_target_for_one_record_is_retryable_and_isolated() -> None:
    world = build_world()
    seed(world, 3)
    world.rest.reject_next(RemoteUnavailable("timeout"))
    job = await world.add_job()
    assert job.id is not None
    run = await world.runner.run(job.id)
    assert run.counters == RunCounters(created=2, failed=1)
    [error] = await world.runs.list_errors(run.id)
    assert (error.kind, error.retryable) == (ErrorKind.REMOTE, True)


async def test_auth_error_aborts_the_run_as_failed() -> None:
    world = build_world()
    seed(world, 5)
    world.rest.reject_next(RemoteAuthError("401"))
    job = await world.add_job(batch_size=2)
    assert job.id is not None
    run = await world.runner.run(job.id)
    assert run.status is RunStatus.FAILED
    assert run.error is not None and "authentication" in run.error.lower()
    assert world.rest.create_calls == 1  # nothing after the auth failure was attempted
    assert run.finished_at is not None


async def test_auth_error_building_an_endpoint_fails_the_run() -> None:
    world = build_world()
    seed(world)
    world.auth_failure = RemoteAuthError("bad token")
    job = await world.add_job()
    assert job.id is not None
    run = await world.runner.run(job.id)
    assert run.status is RunStatus.FAILED and run.error is not None


async def test_missing_target_resource_fails_the_run_not_each_record() -> None:
    world = build_world()
    seed(world)
    job = await world.add_job()
    assert job.id is not None
    job = await world.jobs.update(
        dataclasses.replace(job, target=dataclasses.replace(job.target, resource="ghost"))
    )
    run = await world.runner.run(job.id or 0)
    assert run.status is RunStatus.FAILED and run.counters.failed == 0


async def test_dry_run_writes_nothing_and_reports_would_counters_with_a_sample() -> None:
    world = build_world(sample_limit=2)
    seed(world, 4)
    job = await world.add_job()
    assert job.id is not None
    await world.runner.run(job.id)
    await world.odoo.update("customers", "1", {"name": "Changed"})
    world.odoo.seed("customers", {"name": "New", "email": "new@x.com"})
    world.odoo.seed("customers", {"name": "New2", "email": "new2@x.com"})
    before = (world.rest.create_calls, world.rest.update_calls, len(world.rest.records["clients"]))
    xrefs_before = await world.xrefs.list(job.id)

    run = await world.runner.run(job.id, dry_run=True)

    assert run.dry_run is True
    assert run.counters == RunCounters(created=2, updated=1, skipped=3)
    assert (
        world.rest.create_calls,
        world.rest.update_calls,
        len(world.rest.records["clients"]),
    ) == before
    assert await world.xrefs.list(job.id) == xrefs_before
    assert len(run.sample) == 2
    assert {"action", "source_id", "fields"} <= set(run.sample[0])
    assert run.sample[0]["action"] == "update"


async def test_second_active_run_is_rejected() -> None:
    world = build_world()
    seed(world)
    job = await world.add_job()
    assert job.id is not None
    await world.runs.create(
        job.id,
        "manual",
        dry_run=False,
        started_at=world.clock.now,
        stale_before=world.clock.now - world.config.stale_after,
    )
    with pytest.raises(JobAlreadyRunning):
        await world.runner.run(job.id)


async def test_unknown_job() -> None:
    world = build_world()
    with pytest.raises(SyncJobNotFound):
        await world.runner.run(404)


async def test_exceeding_the_error_threshold_aborts_as_failed() -> None:
    world = build_world(max_errors=2)
    for i in range(6):
        world.odoo.seed("customers", {"name": f"x{i}"})  # no email: mapping error each
    job = await world.add_job(batch_size=10)
    assert job.id is not None
    run = await world.runner.run(job.id)
    assert run.status is RunStatus.FAILED
    assert run.error is not None and "errors" in run.error
    assert run.counters.failed == 3  # aborted right after exceeding the threshold of 2
    assert await world.runs.count_errors(run.id) == 3


async def test_secrets_never_reach_run_errors() -> None:
    world = build_world()
    world.odoo.seed("customers", {"name": "Ana", "email": "a@x.com", "api_key": "S3CRET-KEY"})
    job = await world.add_job()
    assert job.id is not None
    world.rest.reject_when(lambda op, res, f: RecordRejected("nope"))
    # route the secret into the payload: map it too
    from conector_odoo.domain.mapping import Direct
    from tests.mapping.helpers import definition, rule

    await world.mappings.save_new_version(
        definition(
            rule("full_name", Direct("name")),
            rule("email", Direct("email")),
            rule("auth.password", Direct("api_key")),
            rule("api_key", Direct("api_key")),
            name="fwd",
        )
    )
    run = await world.runner.run(job.id)
    assert run.counters.failed == 1
    raw = world.conn.execute("SELECT payload_json, message FROM run_errors").fetchone()
    assert "S3CRET-KEY" not in "".join(str(x) for x in raw)
    [error] = await world.runs.list_errors(run.id)
    assert error.payload is not None
    assert error.payload["fields"]["api_key"] == "***"
    assert error.payload["fields"]["auth"]["password"] == "***"
    assert error.payload["fields"]["email"] == "a@x.com"


async def test_progress_is_checkpointed_after_each_batch() -> None:
    world = build_world(batch_pause=0.5)
    seed(world, 5)
    job = await world.add_job(batch_size=2)
    assert job.id is not None
    seen: list[dict[str, object]] = []

    async def spy() -> None:
        seen.append((await world.last_run()).checkpoint)

    world.on_sleep = spy
    run = await world.runner.run(job.id)
    assert [c["last_id"] for c in seen] == ["2", "4", "5"]
    assert world.sleeps == [0.5, 0.5, 0.5]
    assert run.checkpoint["last_id"] == "5"


async def test_target_record_deleted_remotely_is_recreated() -> None:
    world = build_world()
    seed(world, 2)
    job = await world.add_job()
    assert job.id is not None
    await world.runner.run(job.id)
    del world.rest.records["clients"]["1"]
    await world.odoo.update("customers", "1", {"name": "Back"})
    run = await world.runner.run(job.id)
    assert run.counters == RunCounters(created=1, skipped=1)
    xref = await world.xrefs.get_target(job.id, "customers", "1")
    assert xref is not None and xref.target_id != "1"
    assert world.rest.records["clients"][xref.target_id].get("full_name") == "Back"


async def test_source_warnings_are_recorded_on_the_run_without_failing_it() -> None:
    world = build_world()
    seed(world)
    world.odoo.warnings = ["list is paginated but strategy is none"]  # type: ignore[attr-defined]
    job = await world.add_job()
    assert job.id is not None
    run = await world.runner.run(job.id)
    assert run.status is RunStatus.SUCCEEDED
    assert run.options["warnings"] == ["list is paginated but strategy is none"]


async def test_a_run_without_source_warnings_has_no_warnings_option() -> None:
    world = build_world()
    seed(world)
    job = await world.add_job()
    assert job.id is not None
    run = await world.runner.run(job.id)
    assert "warnings" not in run.options
