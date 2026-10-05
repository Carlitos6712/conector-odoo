"""Assembly of ``/admin/api``.

Public routes (login/logout) are mounted on their own router. EVERYTHING else is included into
``protected``, whose dependency authenticates, applies the role rule and checks CSRF: a new router
must be added there, and the route-table tests fail if any route answers an anonymous caller.
"""

from fastapi import APIRouter, Depends, FastAPI

from conector_odoo.infrastructure.admin_api.deps import authorize
from conector_odoo.infrastructure.admin_api.routers import auth, users

PREFIX = "/admin/api"


def include_admin_api(app: FastAPI) -> None:
    public = APIRouter(prefix=PREFIX)
    public.include_router(auth.router)
    app.include_router(public)

    protected = APIRouter(prefix=PREFIX, dependencies=[Depends(authorize)])
    protected.include_router(users.router)
    app.include_router(protected)
