"""``/admin/api/jobs``: sync job CRUD and manual runs.

Every change refreshes the in-process scheduler so a new or edited schedule applies at once.
"""

from fastapi import APIRouter, Response

from conector_odoo.infrastructure.admin_api.deps import AdminDep
from conector_odoo.infrastructure.admin_api.schemas.jobs import (
    JobIn,
    JobListOut,
    JobOut,
    TriggerRunIn,
)
from conector_odoo.infrastructure.admin_api.schemas.runs import RunOut

router = APIRouter(prefix="/jobs", tags=["admin-jobs"])


@router.get("")
async def list_jobs(admin: AdminDep) -> JobListOut:
    jobs = await admin.jobs.list.execute()
    return JobListOut(
        items=[JobOut.of(job, admin.scheduler.next_fire(job.id or 0)) for job in jobs]
    )


@router.post("", status_code=201)
async def create_job(body: JobIn, admin: AdminDep) -> JobOut:
    job = await admin.jobs.create.execute(body.to_domain())
    await admin.scheduler.refresh()
    return JobOut.of(job, admin.scheduler.next_fire(job.id or 0))


@router.get("/{job_id}")
async def get_job(job_id: int, admin: AdminDep) -> JobOut:
    return JobOut.of(await admin.jobs.get.execute(job_id), admin.scheduler.next_fire(job_id))


@router.put("/{job_id}")
async def update_job(job_id: int, body: JobIn, admin: AdminDep) -> JobOut:
    job = await admin.jobs.update.execute(job_id, body.to_domain())
    await admin.scheduler.refresh()
    return JobOut.of(job, admin.scheduler.next_fire(job_id))


@router.delete("/{job_id}", status_code=204)
async def delete_job(job_id: int, admin: AdminDep) -> Response:
    await admin.jobs.delete.execute(job_id)
    await admin.scheduler.refresh()
    return Response(status_code=204)


@router.post("/{job_id}/runs", status_code=202)
async def trigger_run(job_id: int, body: TriggerRunIn, admin: AdminDep) -> RunOut:
    """Start a manual run in the background and return it at once; follow it on ``/runs/{id}``."""
    run = await admin.launcher.trigger(job_id, dry_run=body.dry_run, only_records=body.only_records)
    return RunOut.of(run)
