"""``/admin/api/profiles/{id}/records/{resource}``: browse, create, edit and delete INDIVIDUAL
records of a connected system (for an Odoo profile ``resource`` is the model, e.g. ``res.partner``).

Writes are admin only and CSRF protected by the shared ``authorize`` dependency. There is no
collection-level or filter-based delete on purpose: one record per request.

Writes are also applied to the counterpart of every enabled bidirectional job; the response lists
what happened per job (``propagation``) and a ready-made ``warnings`` list. A counterpart failure
never fails the request: the targeted record is already written.
"""

from fastapi import APIRouter, Query

from conector_odoo.application.records import DEFAULT_LIMIT, MAX_LIMIT, MAX_OFFSET
from conector_odoo.infrastructure.admin_api.deps import AdminDep
from conector_odoo.infrastructure.admin_api.schemas.resources import (
    RecordDeleteOut,
    RecordOut,
    RecordPageOut,
    RecordPatchIn,
    RecordWriteOut,
)

router = APIRouter(prefix="/profiles/{profile_id}/records", tags=["admin-records"])


@router.get("/{resource}")
async def list_records(
    profile_id: int,
    resource: str,
    admin: AdminDep,
    search: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0, le=MAX_OFFSET),
) -> RecordPageOut:
    page = await admin.records.list.execute(
        profile_id, resource, search=search, limit=limit, offset=offset
    )
    return RecordPageOut.of(page)


@router.get("/{resource}/{record_id}")
async def get_record(profile_id: int, resource: str, record_id: str, admin: AdminDep) -> RecordOut:
    return RecordOut.of(await admin.records.get.execute(profile_id, resource, record_id))


@router.post("/{resource}", status_code=201)
async def create_record(
    profile_id: int, resource: str, body: RecordPatchIn, admin: AdminDep
) -> RecordWriteOut:
    """Create ONE record on this profile, then on the counterpart of each bidirectional job."""
    created = await admin.records.create.execute(profile_id, resource, body.fields)
    return RecordWriteOut.from_write(created)


@router.patch("/{resource}/{record_id}")
async def patch_record(
    profile_id: int, resource: str, record_id: str, body: RecordPatchIn, admin: AdminDep
) -> RecordWriteOut:
    """Change fields of ONE record; read-only and unknown fields are rejected (422)."""
    updated = await admin.records.update.execute(profile_id, resource, record_id, body.fields)
    return RecordWriteOut.from_write(updated)


@router.delete("/{resource}/{record_id}")
async def delete_record(
    profile_id: int, resource: str, record_id: str, admin: AdminDep
) -> RecordDeleteOut:
    """Delete ONE record (and its counterparts). Never touches other records, never cascades."""
    result = await admin.records.delete.execute(profile_id, resource, record_id)
    return RecordDeleteOut.of(result)
