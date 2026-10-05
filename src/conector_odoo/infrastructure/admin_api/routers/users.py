"""``/admin/api/users``: user management, admin only."""

from fastapi import APIRouter, Depends, Response

from conector_odoo.infrastructure.admin_api.deps import AdminDep, SessionDep, require_admin
from conector_odoo.infrastructure.admin_api.schemas.auth import (
    UserCreateIn,
    UserListOut,
    UserOut,
    UserPatchIn,
)

router = APIRouter(prefix="/users", tags=["admin-users"], dependencies=[Depends(require_admin)])


@router.get("")
async def list_users(admin: AdminDep) -> UserListOut:
    return UserListOut(items=[UserOut.of(u) for u in await admin.users.list()])


@router.post("", status_code=201)
async def create_user(body: UserCreateIn, admin: AdminDep) -> UserOut:
    return UserOut.of(await admin.users.create(body.username, body.password, body.role))


@router.patch("/{user_id}")
async def update_user(user_id: int, body: UserPatchIn, admin: AdminDep) -> UserOut:
    return UserOut.of(await admin.users.update(user_id, role=body.role, password=body.password))


@router.delete("/{user_id}", status_code=204)
async def delete_user(user_id: int, admin: AdminDep, session: SessionDep) -> Response:
    await admin.users.delete(user_id, acting_user_id=session.user.id)
    return Response(status_code=204)
