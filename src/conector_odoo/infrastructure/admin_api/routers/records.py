"""``/admin/api/profiles/{id}/records/{resource}``: browse, edit and delete INDIVIDUAL records of a
connected system (for an Odoo profile ``resource`` is the model, e.g. ``res.partner``).

Writes are admin only and CSRF protected by the shared ``authorize`` dependency. There is no
collection-level or filter-based delete on purpose: one record per request.
"""

from fastapi import APIRouter, Query, Response

from conector_odoo.application.records import DEFAULT_LIMIT, MAX_LIMIT, MAX_OFFSET
from conector_odoo.infrastructure.admin_api.deps import AdminDep
from conector_odoo.infrastructure.admin_api.schemas.resources import (
    RecordOut,
    RecordPageOut,
    RecordPatchIn,
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


@router.patch("/{resource}/{record_id}")
async def patch_record(
    profile_id: int, resource: str, record_id: str, body: RecordPatchIn, admin: AdminDep
) -> RecordOut:
    """Change fields of ONE record; read-only and unknown fields are rejected (422)."""
    updated = await admin.records.update.execute(profile_id, resource, record_id, body.fields)
    return RecordOut.of(updated)


@router.delete("/{resource}/{record_id}", status_code=204)
async def delete_record(
    profile_id: int, resource: str, record_id: str, admin: AdminDep
) -> Response:
    """Delete ONE record. Never touches other records, never cascades."""
    await admin.records.delete.execute(profile_id, resource, record_id)
    return Response(status_code=204)
