"""Authentication, role and CSRF guards of ``/admin/api``.

Every protected route sits behind ``authorize`` (it is a dependency of the one router all protected
routers are included into, see ``admin_api/router.py``), so a new route is authenticated, CSRF
checked and role checked by default; a route has to opt OUT by living on the public auth router.

Roles: any signed-in user may call safe methods (GET/HEAD/OPTIONS); every other method needs the
``admin`` role. State-changing requests must also echo the session's CSRF token in
``X-CSRF-Token`` (constant-time comparison); cookies alone never authorise a change.
"""

import hmac
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, Request, Response

from conector_odoo.application.auth import CurrentSession
from conector_odoo.config import Settings
from conector_odoo.domain.auth import AdminUser, Role
from conector_odoo.domain.client_ip import resolve_client_ip
from conector_odoo.domain.errors import AdminForbidden, CsrfInvalid
from conector_odoo.infrastructure.admin_api.services import AdminServices
from conector_odoo.infrastructure.api.dependencies import get_settings

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
# The identity used when ``ADMIN_AUTH_DISABLED`` is on. The id is never stored anywhere.
_DISABLED_AUTH_USER = AdminUser(id=0, username="local-admin", role=Role.ADMIN, created_at=_EPOCH)
_DISABLED_AUTH_CSRF = "auth-disabled"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
CSRF_HEADER = "X-CSRF-Token"


def get_admin(request: Request) -> AdminServices:
    admin: AdminServices = request.app.state.admin
    return admin


AdminDep = Annotated[AdminServices, Depends(get_admin)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def client_ip(request: Request, settings: SettingsDep) -> str:
    """The address login throttling is keyed on (see ``resolve_client_ip`` for the proxy rules)."""
    peer = request.client.host if request.client else None
    return resolve_client_ip(
        peer, request.headers.getlist("x-forwarded-for"), settings.trusted_proxy_count
    )


ClientIpDep = Annotated[str, Depends(client_ip)]


async def current_session(
    request: Request, response: Response, admin: AdminDep, settings: SettingsDep
) -> CurrentSession:
    """The signed-in session or ``SessionInvalid`` (401). Admin responses are never cached."""
    response.headers["Cache-Control"] = "no-store"
    if settings.admin_auth_disabled:
        expires_at = datetime.now(UTC) + timedelta(seconds=settings.admin_session_ttl_seconds)
        return CurrentSession(_DISABLED_AUTH_USER, _DISABLED_AUTH_CSRF, expires_at)
    token = request.cookies.get(settings.admin_cookie_name, "")
    return await admin.auth.authenticate(token)


SessionDep = Annotated[CurrentSession, Depends(current_session)]


def _check_csrf(request: Request, session: CurrentSession, settings: Settings) -> None:
    if settings.admin_auth_disabled:
        return  # no cookie session exists, so there is nothing for a forged request to ride on
    provided = request.headers.get(CSRF_HEADER, "").encode()
    if not hmac.compare_digest(provided, session.csrf_token.encode()):
        raise CsrfInvalid("missing or invalid CSRF token")


async def authorize(request: Request, session: SessionDep, settings: SettingsDep) -> CurrentSession:
    if request.method not in SAFE_METHODS:
        if session.user.role is not Role.ADMIN:
            raise AdminForbidden("this operation requires the admin role")
        _check_csrf(request, session, settings)
    return session


AuthorizedDep = Annotated[CurrentSession, Depends(authorize)]


async def authorize_self_service(
    request: Request, session: SessionDep, settings: SettingsDep
) -> CurrentSession:
    """The one explicit exception to "writes need the admin role": a user acting on their OWN
    account (password change). Any role may call it, but it still needs a session and CSRF."""
    _check_csrf(request, session, settings)
    return session


SelfServiceDep = Annotated[CurrentSession, Depends(authorize_self_service)]


async def require_admin(session: AuthorizedDep) -> CurrentSession:
    """For routes that even a read-only operator must not see (e.g. the user list)."""
    if session.user.role is not Role.ADMIN:
        raise AdminForbidden("this operation requires the admin role")
    return session
