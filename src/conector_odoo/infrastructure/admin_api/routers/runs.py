"""``/admin/api/runs`` and ``/admin/api/dashboard``: run history, control and the summary."""

from datetime import datetime

from fastapi import APIRouter, Query

from conector_odoo.domain.sync_runs import RunFilter, RunStatus
from conector_odoo.infrastructure.admin_api.deps import AdminDep
from conector_odoo.infrastructure.admin_api.schemas.runs import (
    DashboardOut,
    RunDetailOut,
    RunErrorListOut,
    RunErrorOut,
    RunListOut,
    RunOut,
)

router = APIRouter(tags=["admin-runs"])


@router.get("/dashboard")
async def dashboard(admin: AdminDep) -> DashboardOut:
    return DashboardOut.of(await admin.dashboard.execute())


@router.get("/runs")
async def list_runs(
    admin: AdminDep,
    job_id: int | None = None,
    status: RunStatus | None = None,
    started_from: datetime | None = None,
    started_to: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> RunListOut:
    run_filter = RunFilter(job_id, status, started_from, started_to)
    runs = await admin.runs.list.execute(run_filter, limit, offset)
    return RunListOut(items=[RunOut.of(run) for run in runs])


@router.get("/runs/{run_id}")
async def get_run(run_id: int, admin: AdminDep) -> RunDetailOut:
    run, error_count = await admin.runs.get.execute(run_id)
    return RunDetailOut.detail(run, error_count)


@router.get("/runs/{run_id}/errors")
async def run_errors(
    run_id: int,
    admin: AdminDep,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    only_unretried: bool = False,
) -> RunErrorListOut:
    errors, total = await admin.runs.errors.execute(
        run_id, limit, offset, only_unretried=only_unretried
    )
    return RunErrorListOut(items=[RunErrorOut.of(e) for e in errors], total=total)


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: int, admin: AdminDep) -> RunOut:
    """Ask an active run to stop at the next batch boundary (409 when it is not active)."""
    await admin.runs.get.execute(run_id)  # 404 for an unknown run
    await admin.launcher.cancel(run_id)
    run, error_count = await admin.runs.get.execute(run_id)
    return RunOut.of(run, error_count)


@router.post("/runs/{run_id}/resume", status_code=202)
async def resume_run(run_id: int, admin: AdminDep) -> RunOut:
    """Continue an interrupted, cancelled or failed run from its checkpoint (in the background)."""
    return RunOut.of(await admin.launcher.resume(run_id))


@router.post("/runs/{run_id}/retry-failed", status_code=202)
async def retry_failed(run_id: int, admin: AdminDep) -> RunOut:
    """Reprocess only the records that failed in this run, as a new linked run."""
    return RunOut.of(await admin.launcher.retry_failed(run_id))
