import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest

from conector_odoo.domain.errors import JobAlreadyRunning, SyncJobNotFound, SyncRunNotFound
from conector_odoo.domain.sync_runs import (
    ErrorKind,
    RunCounters,
    RunErrorData,
    RunFilter,
    RunStatus,
    Side,
    XRef,
)
from conector_odoo.infrastructure.migrations import open_admin_database
from conector_odoo.infrastructure.sync.runs import SqliteSyncRunRepository, SqliteXRefRepository

T0 = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
STALE = timedelta(minutes=15)


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = open_admin_database(":memory:")
    ts = T0.isoformat()
    connection.execute(
        "INSERT INTO connection_profiles (id, name, type, base_url, auth_method, created_at, "
        "updated_at) VALUES (1, 'p', 'rest', 'https://x', 'none', ?, ?)",
        (ts, ts),
    )
    connection.execute(
        "INSERT INTO mappings (id, name, version, definition_json, created_at) "
        "VALUES (1, 'm', 1, '{}', ?)",
        (ts,),
    )
    for job_id in (1, 2):
        connection.execute(
            "INSERT INTO sync_jobs (id, name, source_profile_id, target_profile_id, mapping_id, "
            "direction, upsert_key, created_at, updated_at) VALUES (?, ?, 1, 1, 1, 'a_to_b', "
            "'xref', ?, ?)",
            (job_id, f"j{job_id}", ts, ts),
        )
    yield connection
    connection.close()


async def start(repo: SqliteSyncRunRepository, job_id: int = 1, at: datetime = T0):  # type: ignore[no-untyped-def]
    return await repo.create(
        job_id, "manual", dry_run=False, started_at=at, stale_before=at - STALE
    )


async def test_create_returns_running_run_with_defaults(conn: sqlite3.Connection) -> None:
    repo = SqliteSyncRunRepository(conn)
    run = await start(repo)
    assert (run.status, run.trigger, run.dry_run) == (RunStatus.RUNNING, "manual", False)
    assert run.counters == RunCounters()
    assert run.started_at == T0 and run.finished_at is None and run.checkpoint == {}
    assert await repo.get(run.id) == run
    assert await repo.get(999) is None


async def test_second_active_run_for_the_same_job_is_rejected(conn: sqlite3.Connection) -> None:
    repo = SqliteSyncRunRepository(conn)
    await start(repo)
    with pytest.raises(JobAlreadyRunning):
        await start(repo, at=T0 + timedelta(minutes=1))
    other = await start(repo, job_id=2)  # another job is independent
    assert other.job_id == 2
    with pytest.raises(SyncJobNotFound):
        await start(repo, job_id=404)


async def test_finished_or_stale_runs_do_not_block(conn: sqlite3.Connection) -> None:
    repo = SqliteSyncRunRepository(conn)
    first = await start(repo)
    await repo.finish(first.id, RunStatus.SUCCEEDED, T0 + timedelta(minutes=1), RunCounters())
    second = await start(repo, at=T0 + timedelta(minutes=2))
    later = (
        T0 + timedelta(minutes=2) + STALE + timedelta(seconds=1)
    )  # second crashed (no heartbeat)
    third = await start(repo, at=later)
    assert third.id != second.id


async def test_progress_heartbeat_keeps_a_run_alive(conn: sqlite3.Connection) -> None:
    repo = SqliteSyncRunRepository(conn)
    run = await start(repo)
    beat = T0 + timedelta(minutes=14)
    await repo.save_progress(run.id, RunCounters(created=2, skipped=1), {"pass": "forward"}, beat)
    saved = await repo.get(run.id)
    assert saved is not None
    assert saved.counters == RunCounters(created=2, skipped=1)
    assert saved.checkpoint == {"pass": "forward"} and saved.heartbeat_at == beat
    with pytest.raises(JobAlreadyRunning):
        await start(repo, at=T0 + timedelta(minutes=20))


async def test_finish_records_status_duration_error_and_sample(conn: sqlite3.Connection) -> None:
    repo = SqliteSyncRunRepository(conn)
    run = await start(repo)
    end = T0 + timedelta(seconds=90)
    await repo.finish(
        run.id,
        RunStatus.PARTIAL,
        end,
        RunCounters(created=1, failed=2, conflicts=1),
        error="boom",
        sample=[{"id": "1"}],
    )
    done = await repo.get(run.id)
    assert done is not None
    assert (done.status, done.finished_at, done.duration_seconds) == (RunStatus.PARTIAL, end, 90.0)
    assert (done.error, done.sample, done.counters.conflicts) == ("boom", [{"id": "1"}], 1)


async def test_cancel_flag_only_on_active_runs_and_reopen(conn: sqlite3.Connection) -> None:
    repo = SqliteSyncRunRepository(conn)
    run = await start(repo)
    assert not await repo.is_cancel_requested(run.id)
    assert await repo.request_cancel(run.id)
    assert await repo.is_cancel_requested(run.id)
    await repo.finish(run.id, RunStatus.CANCELLED, T0, RunCounters())
    assert not await repo.request_cancel(run.id)
    reopened = await repo.reopen(run.id, heartbeat_at=T0, stale_before=T0 - STALE)
    assert reopened.status is RunStatus.RUNNING and not reopened.cancel_requested
    with pytest.raises(SyncRunNotFound):
        await repo.reopen(404, heartbeat_at=T0, stale_before=T0 - STALE)


async def test_reopen_is_refused_when_another_run_of_the_job_is_active(
    conn: sqlite3.Connection,
) -> None:
    repo = SqliteSyncRunRepository(conn)
    first = await start(repo)
    await repo.finish(first.id, RunStatus.FAILED, T0, RunCounters())
    await start(repo, at=T0 + timedelta(minutes=1))
    with pytest.raises(JobAlreadyRunning):
        await repo.reopen(first.id, heartbeat_at=T0, stale_before=T0 - STALE)


async def test_errors_are_appended_in_batches_and_paged(conn: sqlite3.Connection) -> None:
    repo = SqliteSyncRunRepository(conn)
    run = await start(repo)
    await repo.add_errors(run.id, [])
    await repo.add_errors(
        run.id,
        [
            RunErrorData("a", "bad", Side.SOURCE, ErrorKind.REJECTED, False, {"name": "x"}),
            RunErrorData("b", "down", Side.TARGET, ErrorKind.REMOTE, True),
            RunErrorData(None, "generic"),
        ],
    )
    assert await repo.count_errors(run.id) == 3
    page = await repo.list_errors(run.id, limit=2)
    assert [e.record_ref for e in page] == ["a", "b"]
    first = page[0]
    assert (first.kind, first.retryable, first.retried, first.payload) == (
        ErrorKind.REJECTED,
        False,
        False,
        {"name": "x"},
    )
    assert page[1].side is Side.TARGET
    assert [e.record_ref for e in await repo.list_errors(run.id, limit=2, offset=2)] == [None]
    await repo.mark_errors_retried(run.id, "source", ["a"])
    pending = await repo.list_errors(run.id, only_unretried=True)
    assert [e.record_ref for e in pending] == ["b", None]


async def test_list_runs_filters_by_job_status_and_dates_newest_first(
    conn: sqlite3.Connection,
) -> None:
    repo = SqliteSyncRunRepository(conn)
    a = await start(repo, 1, T0)
    await repo.finish(a.id, RunStatus.SUCCEEDED, T0, RunCounters())
    b = await start(repo, 1, T0 + timedelta(days=1))
    await repo.finish(b.id, RunStatus.FAILED, T0, RunCounters())
    c = await start(repo, 2, T0 + timedelta(days=2))
    assert [r.id for r in await repo.list_runs(RunFilter())] == [c.id, b.id, a.id]
    assert [r.id for r in await repo.list_runs(RunFilter(job_id=1))] == [b.id, a.id]
    assert [r.id for r in await repo.list_runs(RunFilter(status=RunStatus.FAILED))] == [b.id]
    window = RunFilter(started_from=T0 + timedelta(hours=1), started_to=T0 + timedelta(days=1))
    assert [r.id for r in await repo.list_runs(window)] == [b.id]
    assert [r.id for r in await repo.list_runs(RunFilter(), limit=1, offset=1)] == [b.id]


async def test_xref_round_trip_lookup_both_ways_and_upsert(conn: sqlite3.Connection) -> None:
    repo = SqliteXRefRepository(conn)
    assert await repo.get_target(1, "customers", "s1") is None
    ref = XRef(1, "customers", "s1", "t1", "h1", None, T0)
    await repo.upsert(ref)
    assert await repo.get_target(1, "customers", "s1") == ref
    assert await repo.get_source(1, "customers", "t1") == ref
    updated = XRef(1, "customers", "s1", "t1", "h2", "r2", T0 + timedelta(hours=1))
    await repo.upsert(updated)
    assert await repo.get_target(1, "customers", "s1") == updated
    await repo.upsert(XRef(1, "orders", "s1", "t9", "h", None, T0))
    await repo.upsert(XRef(2, "customers", "s1", "t7", "h", None, T0))
    assert len(await repo.list(1)) == 2
    assert [x.target_id for x in await repo.list(1, "customers")] == ["t1"]
    assert await repo.get_target(2, "customers", "s1") is not None
    assert len(await repo.list(1, limit=1, offset=1)) == 1
