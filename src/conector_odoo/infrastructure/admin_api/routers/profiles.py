"""``/admin/api/profiles``: connection profiles and their connection tests.

Secrets are write-only: no response ever contains one, only ``has_secret`` flags. Testing a
connection contacts a remote system with the stored credentials, so it is a POST (admin only).
"""

from fastapi import APIRouter, Response

from conector_odoo.infrastructure.admin_api.deps import AdminDep
from conector_odoo.infrastructure.admin_api.schemas.profiles import (
    ConnectionTestOut,
    ProfileIn,
    ProfileListOut,
    ProfileOut,
)

router = APIRouter(prefix="/profiles", tags=["admin-profiles"])


@router.get("")
async def list_profiles(admin: AdminDep) -> ProfileListOut:
    return ProfileListOut(items=[ProfileOut.of(v) for v in await admin.profiles.list.execute()])


@router.post("", status_code=201)
async def create_profile(body: ProfileIn, admin: AdminDep) -> ProfileOut:
    view = await admin.profiles.create.execute(body.to_domain(), body.secrets_domain())
    return ProfileOut.of(view)


@router.post("/test")
async def test_draft(body: ProfileIn, admin: AdminDep) -> ConnectionTestOut:
    """Probe an unsaved profile (nothing is stored)."""
    result = await admin.profiles.test.test_draft(body.to_domain(), body.secrets_domain())
    return ConnectionTestOut.of(result)


@router.get("/{profile_id}")
async def get_profile(profile_id: int, admin: AdminDep) -> ProfileOut:
    return ProfileOut.of(await admin.profiles.get.execute(profile_id))


@router.put("/{profile_id}")
async def update_profile(profile_id: int, body: ProfileIn, admin: AdminDep) -> ProfileOut:
    view = await admin.profiles.update.execute(profile_id, body.to_domain(), body.secrets_domain())
    return ProfileOut.of(view)


@router.delete("/{profile_id}", status_code=204)
async def delete_profile(profile_id: int, admin: AdminDep) -> Response:
    await admin.profiles.delete.execute(profile_id)
    return Response(status_code=204)


@router.post("/{profile_id}/test")
async def test_saved(profile_id: int, admin: AdminDep) -> ConnectionTestOut:
    result = await admin.profiles.test.test_saved(profile_id)
    return ConnectionTestOut.of(result)
