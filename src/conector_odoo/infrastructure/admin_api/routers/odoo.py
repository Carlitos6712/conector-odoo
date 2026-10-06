"""``/admin/api/odoo/active``: which Odoo connection the connector uses, switchable at runtime.

Any signed-in user may read it; changing it needs the admin role and CSRF (the shared guard).
Activating probes the profile BEFORE swapping, so a wrong profile never breaks a working
connection: it answers 422 ``odoo_activation_failed`` naming the failing step.
"""

from fastapi import APIRouter

from conector_odoo.infrastructure.admin_api.deps import AdminDep
from conector_odoo.infrastructure.admin_api.schemas.odoo import ActivateOdooIn, ActiveOdooOut

router = APIRouter(prefix="/odoo", tags=["admin-odoo"])


@router.get("/active")
async def get_active(admin: AdminDep) -> ActiveOdooOut:
    return ActiveOdooOut.of(await admin.active_odoo.status())


@router.put("/active")
async def activate(body: ActivateOdooIn, admin: AdminDep) -> ActiveOdooOut:
    return ActiveOdooOut.of(await admin.active_odoo.activate(body.profile_id))


@router.delete("/active")
async def disconnect(admin: AdminDep) -> ActiveOdooOut:
    """Forget the active profile; the env connection (if configured) takes over, else none."""
    return ActiveOdooOut.of(await admin.active_odoo.clear())
