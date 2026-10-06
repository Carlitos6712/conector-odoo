"""``/admin/api/auth``: login, logout and the current session (the only unguarded routes)."""

from fastapi import APIRouter, Request, Response

from conector_odoo.config import Settings
from conector_odoo.infrastructure.admin_api.deps import (
    AdminDep,
    SelfServiceDep,
    SessionDep,
    SettingsDep,
)
from conector_odoo.infrastructure.admin_api.schemas.auth import (
    LoginIn,
    PasswordChangeIn,
    SessionOut,
    UserOut,
)

COOKIE_PATH = "/admin/api"

router = APIRouter(prefix="/auth", tags=["admin-auth"])


def _issue_cookie(response: Response, settings: Settings, token: str) -> None:
    response.set_cookie(
        settings.admin_cookie_name,
        token,
        max_age=settings.admin_session_ttl_seconds,
        httponly=True,
        secure=settings.admin_cookie_secure,
        samesite=settings.admin_cookie_samesite,
        path=COOKIE_PATH,
    )
    response.headers["Cache-Control"] = "no-store"


@router.post("/login")
async def login(
    body: LoginIn,
    request: Request,
    response: Response,
    admin: AdminDep,
    settings: SettingsDep,
) -> SessionOut:
    """Sign in. Any session cookie the browser already holds is destroyed (rotation)."""
    result = await admin.auth.login(
        body.username,
        body.password,
        previous_token=request.cookies.get(settings.admin_cookie_name),
    )
    _issue_cookie(response, settings, result.token)
    return SessionOut(
        user=UserOut.of(result.user), csrf_token=result.csrf_token, expires_at=result.expires_at
    )


@router.post("/password")
async def change_password(
    body: PasswordChangeIn,
    response: Response,
    admin: AdminDep,
    settings: SettingsDep,
    session: SelfServiceDep,
) -> SessionOut:
    """Change the signed-in user's own password (any role). Every session of the user is revoked
    and the caller gets a fresh cookie and CSRF token."""
    result = await admin.auth.change_password(
        session.user, body.current_password, body.new_password
    )
    _issue_cookie(response, settings, result.token)
    return SessionOut(
        user=UserOut.of(result.user), csrf_token=result.csrf_token, expires_at=result.expires_at
    )


@router.post("/logout", status_code=204)
async def logout(request: Request, admin: AdminDep, settings: SettingsDep) -> Response:
    """Destroy the session server-side and clear the cookie. Idempotent, needs no session."""
    await admin.auth.logout(request.cookies.get(settings.admin_cookie_name, ""))
    response = Response(status_code=204, headers={"Cache-Control": "no-store"})
    response.delete_cookie(
        settings.admin_cookie_name,
        path=COOKIE_PATH,
        httponly=True,
        secure=settings.admin_cookie_secure,
        samesite=settings.admin_cookie_samesite,
    )
    return response


@router.get("/me")
async def me(session: SessionDep) -> SessionOut:
    return SessionOut(
        user=UserOut.of(session.user),
        csrf_token=session.csrf_token,
        expires_at=session.expires_at,
    )
