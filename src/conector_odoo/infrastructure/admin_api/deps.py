"""Authentication, role and CSRF guards of ``/admin/api``.

Every protected route sits behind ``authorize`` (it is a dependency of the one router all protected
routers are included into, see ``admin_api/router.py``), so a new route is authenticated, CSRF
checked and role checked by default; a route has to opt OUT by living on the public auth router.

Roles: any signed-in user may call safe methods (GET/HEAD/OPTIONS); every other method needs the
``admin`` role. State-changing requests must also echo the session's CSRF token in
``X-CSRF-Token`` (constant-time comparison); cookies alone never authorise a change.
"""

import hmac
from typing import Annotated

from fastapi import Depends, Request, Response

from conector_odoo.application.auth import CurrentSession
from conector_odoo.config import Settings
from conector_odoo.domain.auth import Role
from conector_odoo.domain.errors import AdminForbidden, CsrfInvalid
from conector_odoo.infrastructure.admin_api.services import AdminServices
from conector_odoo.infrastructure.api.dependencies import get_settings

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
CSRF_HEADER = "X-CSRF-Token"


def get_admin(request: Request) -> AdminServices:
    admin: AdminServices = request.app.state.admin
    return admin


AdminDep = Annotated[AdminServices, Depends(get_admin)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


async def current_session(
    request: Request, response: Response, admin: AdminDep, settings: SettingsDep
) -> CurrentSession:
    """The signed-in session or ``SessionInvalid`` (401). Admin responses are never cached."""
    response.headers["Cache-Control"] = "no-store"
    token = request.cookies.get(settings.admin_cookie_name, "")
    return await admin.auth.authenticate(token)


SessionDep = Annotated[CurrentSession, Depends(current_session)]


def _check_csrf(request: Request, session: CurrentSession) -> None:
    provided = request.headers.get(CSRF_HEADER, "").encode()
    if not hmac.compare_digest(provided, session.csrf_token.encode()):
        raise CsrfInvalid("missing or invalid CSRF token")


async def authorize(request: Request, session: SessionDep) -> CurrentSession:
    if request.method not in SAFE_METHODS:
        if session.user.role is not Role.ADMIN:
            raise AdminForbidden("this operation requires the admin role")
        _check_csrf(request, session)
    return session


AuthorizedDep = Annotated[CurrentSession, Depends(authorize)]


async def authorize_self_service(request: Request, session: SessionDep) -> CurrentSession:
    """The one explicit exception to "writes need the admin role": a user acting on their OWN
    account (password change). Any role may call it, but it still needs a session and CSRF."""
    _check_csrf(request, session)
    return session


SelfServiceDep = Annotated[CurrentSession, Depends(authorize_self_service)]


async def require_admin(session: AuthorizedDep) -> CurrentSession:
    """For routes that even a read-only operator must not see (e.g. the user list)."""
    if session.user.role is not Role.ADMIN:
        raise AdminForbidden("this operation requires the admin role")
    return session
