from typing import Any

import pytest

from conector_odoo.domain.errors import (
    JobAlreadyRunning,
    RecordRejected,
    RemoteAuthError,
    RunNotResumable,
    SyncRunNotFound,
)
from conector_odoo.domain.sync_runs import ErrorKind, RunCounters, RunStatus
from tests.sync.harness import World, build_world


class Crash(BaseException):
    """Simulates a killed process: not an ``Exception``, so nothing in the runner catches it."""


def seed(world: World, n: int) -> None:
    for i in range(1, n + 1):
        world.odoo.seed("customers", {"name": f"Ana {i}", "email": f"ana{i}@x.com"})


def fail_once_on(world: World, email: str, error: BaseException) -> dict[str, bool]:
    armed = {"on": True}
    world.rest.reject_when(
        lambda op, res, f: error if armed["on"] and f.get("email") == email else None
    )
    return armed


async def crashed_run(world: World, job_id: int) -> int:
    with pytest.raises(Crash):
        await world.runner.run(job_id)
    return (await world.last_run()).id


async def test_crashed_run_stays_running_with_its_last_checkpoint() -> None:
    world = build_world()
    seed(world, 6)
    fail_once_on(world, "ana5@x.com", Crash())
    job = await world.add_job(batch_size=2)
    assert job.id is not None
    run_id = await crashed_run(world, job.id)
    run = await world.runs.get(run_id)
    assert run is not None
    assert run.status is RunStatus.RUNNING and run.finished_at is None
    assert run.checkpoint["last_id"] == "4" and run.counters.created == 4
    with pytest.raises(JobAlreadyRunning):  # not yet considered crashed
        await world.runner.run(job.id)


async def test_resume_after_crash_continues_from_the_checkpoint_without_duplicates() -> None:
    world = build_world()
    seed(world, 6)
    armed = fail_once_on(world, "ana5@x.com", Crash())
    job = await world.add_job(batch_size=2)
    assert job.id is not None
    run_id = await crashed_run(world, job.id)
    armed["on"] = False
    with pytest.raises(RunNotResumable):  # heartbeat is fresh
        await world.runner.resume(run_id)

    world.clock.advance(minutes=30)
    world.rebuild()  # a new process
    run = await world.runner.resume(run_id)

    assert run.id == run_id and run.status is RunStatus.SUCCEEDED
    assert run.counters == RunCounters(created=6)
    assert len(world.rest.records["clients"]) == 6
    assert world.rest.create_calls == 5 + 2  # 4 ok + the crashed attempt, then records 5 and 6


async def test_stale_running_run_does_not_block_a_new_run() -> None:
    world = build_world()
    seed(world, 2)
    armed = fail_once_on(world, "ana2@x.com", Crash())
    job = await world.add_job()
    assert job.id is not None
    await crashed_run(world, job.id)
    armed["on"] = False
    world.clock.advance(minutes=30)
    run = await world.runner.run(job.id)
    assert run.status is RunStatus.SUCCEEDED
    assert run.counters == RunCounters(created=1, skipped=1)  # record 1 survived the crash


async def test_resume_a_failed_run_after_the_cause_is_fixed() -> None:
    world = build_world()
    seed(world, 5)
    armed = fail_once_on(world, "ana3@x.com", RemoteAuthError("expired"))
    job = await world.add_job(batch_size=2)
    assert job.id is not None
    failed = await world.runner.run(job.id)
    assert failed.status is RunStatus.FAILED and failed.counters.created == 2
    armed["on"] = False
    run = await world.runner.resume(failed.id)
    assert run.status is RunStatus.SUCCEEDED and run.error is None
    assert run.counters.created == 5 and len(world.rest.records["clients"]) == 5


async def test_resume_replays_the_pass_when_the_checkpoint_record_vanished() -> None:
    world = build_world()
    seed(world, 3)
    armed = fail_once_on(world, "ana3@x.com", RemoteAuthError("expired"))
    job = await world.add_job(batch_size=1)
    assert job.id is not None
    failed = await world.runner.run(job.id)
    armed["on"] = False
    world.conn.execute(
        'UPDATE sync_runs SET checkpoint_json = \'{"pass": "forward", "last_id": "gone"}\''
    )
    run = await world.runner.resume(failed.id)
    assert run.status is RunStatus.SUCCEEDED
    assert len(world.rest.records["clients"]) == 3  # idempotent: xref hashes prevent duplicates


async def test_resume_rejects_finished_and_unknown_runs() -> None:
    world = build_world()
    seed(world, 1)
    job = await world.add_job()
    assert job.id is not None
    done = await world.runner.run(job.id)
    with pytest.raises(RunNotResumable):
        await world.runner.resume(done.id)
    with pytest.raises(SyncRunNotFound):
        await world.runner.resume(404)


async def retry_setup(world: World) -> tuple[int, dict[str, bool]]:
    seed(world, 4)
    flag = {"on": True}
    world.rest.reject_when(
        lambda op, res, f: (
            RecordRejected("bad email") if flag["on"] and f.get("email") == "ana2@x.com" else None
        )
    )
    job = await world.add_job()
    assert job.id is not None
    return job.id, flag


async def test_retry_failed_reprocesses_only_failed_records_and_marks_them_retried() -> None:
    world = build_world()
    job_id, flag = await retry_setup(world)
    first = await world.runner.run(job_id)
    assert first.counters == RunCounters(created=3, failed=1)
    flag["on"] = False
    gets_before = world.odoo.get_calls

    retry = await world.runner.retry_failed(first.id)

    assert retry.parent_run_id == first.id and retry.id != first.id
    assert retry.status is RunStatus.SUCCEEDED and retry.counters == RunCounters(created=1)
    assert world.odoo.get_calls - gets_before == 1  # re-fetched just the failed id
    assert len(world.rest.records["clients"]) == 4
    [error] = await world.runs.list_errors(first.id)
    assert error.retried is True
    with pytest.raises(RunNotResumable):  # nothing left to retry
        await world.runner.retry_failed(first.id)


async def test_retry_failed_with_a_persistent_failure_keeps_the_error_open() -> None:
    world = build_world()
    job_id, _ = await retry_setup(world)
    first = await world.runner.run(job_id)
    retry = await world.runner.retry_failed(first.id)
    assert retry.counters == RunCounters(failed=1) and retry.status is RunStatus.FAILED
    [original] = await world.runs.list_errors(first.id)
    assert original.retried is False
    [again] = await world.runs.list_errors(retry.id)
    assert (again.record_ref, again.kind) == ("2", ErrorKind.REJECTED)
    third = await world.runner.retry_failed(first.id)  # can be retried again
    assert third.parent_run_id == first.id


async def test_retry_failed_reports_a_record_deleted_at_the_source() -> None:
    world = build_world()
    job_id, _ = await retry_setup(world)
    first = await world.runner.run(job_id)
    del world.odoo.records["customers"]["2"]
    retry = await world.runner.retry_failed(first.id)
    [error] = await world.runs.list_errors(retry.id)
    assert (error.record_ref, error.kind) == ("2", ErrorKind.NOT_FOUND)


async def test_retry_failed_unknown_run() -> None:
    world = build_world()
    with pytest.raises(SyncRunNotFound):
        await world.runner.retry_failed(404)


async def test_only_records_limits_the_run_to_those_source_ids() -> None:
    world = build_world()
    seed(world, 4)
    job = await world.add_job()
    assert job.id is not None
    run = await world.runner.run(job.id, only_records=["2", "4"])
    assert run.counters == RunCounters(created=2)
    assert [r.get("full_name") for r in world.rest.records["clients"].values()] == [
        "Ana 2",
        "Ana 4",
    ]


async def start_cancelling_after_first_batch(world: World) -> None:
    async def cancel() -> None:
        run = await world.last_run()
        if not run.finished_at:
            await world.runner.cancel(run.id)

    world.on_sleep = cancel


async def test_cancel_stops_between_batches_and_the_run_can_be_resumed() -> None:
    world = build_world(batch_pause=0.1)
    seed(world, 5)
    job = await world.add_job(batch_size=2)
    assert job.id is not None
    await start_cancelling_after_first_batch(world)
    run = await world.runner.run(job.id)
    assert run.status is RunStatus.CANCELLED and run.finished_at is not None
    assert run.counters.created == 2 and run.checkpoint["last_id"] == "2"
    assert len(world.rest.records["clients"]) == 2

    world.on_sleep = None
    resumed = await world.runner.resume(run.id)
    assert resumed.status is RunStatus.SUCCEEDED and resumed.counters.created == 5


async def test_cancel_returns_false_for_finished_runs_and_closes_crashed_ones() -> None:
    world = build_world()
    seed(world, 2)
    job = await world.add_job()
    assert job.id is not None
    done = await world.runner.run(job.id)
    assert await world.runner.cancel(done.id) is False

    world.rest.records["clients"].clear()
    world.conn.execute("DELETE FROM xref")
    fail_once_on(world, "ana2@x.com", Crash())
    crashed = await crashed_run(world, job.id)
    world.clock.advance(minutes=30)
    assert await world.runner.cancel(crashed) is True
    after = await world.runs.get(crashed)
    assert after is not None and after.status is RunStatus.CANCELLED
    assert after.finished_at is not None


async def test_unexpected_internal_error_fails_the_run_and_propagates() -> None:
    world = build_world()
    seed(world, 2)

    def boom(op: str, res: str, f: dict[str, Any]) -> BaseException | None:
        return RuntimeError("bug")

    world.rest.reject_when(boom)
    job = await world.add_job()
    assert job.id is not None
    with pytest.raises(RuntimeError):
        await world.runner.run(job.id)
    run = await world.last_run()
    assert run.status is RunStatus.FAILED and run.error == "internal error: RuntimeError"
