"""``GetDashboard.recent_failures`` hides failures superseded by a later real success."""

import builtins
from datetime import UTC, datetime, timedelta
from typing import Any

from conector_odoo.application.dashboard import GetDashboard
from conector_odoo.domain.sync_runs import RunCounters, RunFilter, RunStatus, SyncRun

NOW = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)


def run(
    run_id: int, job_id: int, status: RunStatus, hours_ago: int, *, dry: bool = False
) -> SyncRun:
    return SyncRun(
        id=run_id,
        job_id=job_id,
        status=status,
        trigger="manual",
        dry_run=dry,
        counters=RunCounters(),
        started_at=NOW - timedelta(hours=hours_ago),
    )


class FakeRuns:
    def __init__(self, runs: list[SyncRun]) -> None:
        self._runs = runs

    async def list_runs(
        self, run_filter: RunFilter, limit: int = 50, offset: int = 0
    ) -> list[SyncRun]:
        rows = [
            r
            for r in self._runs
            if (run_filter.job_id is None or r.job_id == run_filter.job_id)
            and (run_filter.status is None or r.status == run_filter.status)
            and (run_filter.started_from is None or r.started_at >= run_filter.started_from)
        ]
        rows.sort(key=lambda r: r.started_at, reverse=True)
        return rows[offset : offset + limit]


class Empty:
    async def list(self) -> "builtins.list[Any]":
        return []

    async def list_latest(self) -> "builtins.list[Any]":
        return []


async def failures_of(runs: list[SyncRun]) -> list[int]:
    dashboard = GetDashboard(
        Empty(),  # type: ignore[arg-type]
        Empty(),  # type: ignore[arg-type]
        Empty(),  # type: ignore[arg-type]
        FakeRuns(runs),  # type: ignore[arg-type]
        lambda: NOW,
        lambda _job_id: None,
    )
    summary = await dashboard.execute()
    return [r.id for r in summary.recent_failures]


async def test_failure_superseded_by_a_later_success_of_the_same_job_is_hidden() -> None:
    runs = [run(1, 7, RunStatus.FAILED, 5), run(2, 7, RunStatus.SUCCEEDED, 2)]
    assert await failures_of(runs) == []


async def test_failure_without_a_later_success_stays() -> None:
    runs = [run(1, 7, RunStatus.SUCCEEDED, 5), run(2, 7, RunStatus.FAILED, 2)]
    assert await failures_of(runs) == [2]


async def test_a_success_of_another_job_does_not_hide_the_failure() -> None:
    runs = [run(1, 7, RunStatus.FAILED, 5), run(2, 8, RunStatus.SUCCEEDED, 2)]
    assert await failures_of(runs) == [1]


async def test_a_later_dry_run_success_does_not_hide_the_failure() -> None:
    runs = [run(1, 7, RunStatus.FAILED, 5), run(2, 7, RunStatus.SUCCEEDED, 2, dry=True)]
    assert await failures_of(runs) == [1]


async def test_partial_runs_are_hidden_the_same_way() -> None:
    runs = [run(1, 7, RunStatus.PARTIAL, 5), run(2, 7, RunStatus.SUCCEEDED, 2)]
    assert await failures_of(runs) == []
