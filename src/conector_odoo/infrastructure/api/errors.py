"""Exception handlers: domain errors -> HTTP status and an ``ErrorOut`` JSON body."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from conector_odoo.config import Settings
from conector_odoo.domain.errors import (
    AdminForbidden,
    AdminUserInvalid,
    AdminUsernameTaken,
    AdminUserNotFound,
    AuthenticationFailed,
    BatchPartiallyApplied,
    CatalogResourceNotFound,
    ConnectorError,
    CreatedButUnreadable,
    CsrfInvalid,
    CurrentPasswordInvalid,
    JobAlreadyRunning,
    LastAdminError,
    LoginLocked,
    MappingInUse,
    MappingInvalid,
    MappingNotFound,
    OdooAuthError,
    OdooNotFound,
    OdooPermissionError,
    OdooUnavailable,
    OdooValidationError,
    OpenApiImportError,
    ProfileInUse,
    ProfileNameTaken,
    ProfileNotFound,
    ProfileValidationError,
    RecordRejected,
    RemoteAuthError,
    RemoteUnavailable,
    ResourceConfigInvalid,
    ResourceNotFound,
    RunNotResumable,
    SessionInvalid,
    SyncJobInUse,
    SyncJobInvalid,
    SyncJobNameTaken,
    SyncJobNotFound,
    SyncRunNotFound,
    VaultDecryptionError,
    VaultNotConfigured,
)
from conector_odoo.domain.mapping import MappingValidationFailed
from conector_odoo.infrastructure.api.security import ApiKeyError

logger = logging.getLogger(__name__)

# (status, error code); the first matching entry wins, ``ConnectorError`` is the fallback.
_MAPPING: tuple[tuple[type[ConnectorError] | tuple[type[ConnectorError], ...], int, str], ...] = (
    (OdooAuthError, 401, "odoo_auth_error"),
    (OdooPermissionError, 403, "permission_denied"),
    (OdooNotFound, 404, "not_found"),
    (OdooValidationError, 422, "validation_error"),
    (OdooUnavailable, 502, "odoo_unavailable"),
    # -- admin API (/admin/api) -------------------------------------------------------------
    (SessionInvalid, 401, "unauthenticated"),
    (AuthenticationFailed, 401, "invalid_credentials"),
    # 422, not 401: the user IS authenticated, and a 401 would make clients drop the session.
    (CurrentPasswordInvalid, 422, "invalid_current_password"),
    (AdminForbidden, 403, "forbidden"),
    (CsrfInvalid, 403, "csrf_invalid"),
    (
        (
            ProfileNotFound,
            CatalogResourceNotFound,
            MappingNotFound,
            SyncJobNotFound,
            SyncRunNotFound,
            AdminUserNotFound,
        ),
        404,
        "not_found",
    ),
    (ResourceNotFound, 404, "resource_not_found"),
    (
        (
            ProfileNameTaken,
            ProfileInUse,
            MappingInUse,
            SyncJobNameTaken,
            SyncJobInUse,
            JobAlreadyRunning,
            RunNotResumable,
            AdminUsernameTaken,
            LastAdminError,
        ),
        409,
        "conflict",
    ),
    (OpenApiImportError, 422, "import_failed"),
    (
        (
            ProfileValidationError,
            ResourceConfigInvalid,
            MappingInvalid,
            SyncJobInvalid,
            AdminUserInvalid,
            RecordRejected,
        ),
        422,
        "validation_error",
    ),
    (VaultNotConfigured, 503, "vault_not_configured"),
    (VaultDecryptionError, 500, "vault_error"),
    (RemoteAuthError, 502, "remote_auth_error"),
    (RemoteUnavailable, 502, "remote_unavailable"),
)


# Where a freshly created record can be fetched, by Odoo model (used for the 202 ``Location``).
_RESOURCE_PATHS = {"res.partner": "/customers", "sale.order": "/sale-orders"}


def scrub(text: str, settings: Settings) -> str:
    """Mask every configured secret in a message before it leaves the process.

    Settings enforce a minimum secret length, so masking every non-empty value cannot mangle
    ordinary text; a short secret that leaked would be worse than a mangled message.
    """
    secrets = [
        settings.odoo_api_key,
        settings.webhook_secret,
        settings.connector_api_key,
        settings.encryption_key,
        settings.admin_bootstrap_password,
    ]
    for secret in secrets:
        if secret is not None and secret.get_secret_value():
            text = text.replace(secret.get_secret_value(), "***")
    return text


def _body(error: str, detail: str) -> dict[str, str]:
    return {"error": error, "detail": detail}


def _request_id(request: Request) -> str | None:
    # Set by the logging middleware (which also sanitizes it); the raw header is not trusted.
    request_id: str | None = getattr(request.state, "request_id", None)
    return request_id


def _log_failure(
    request: Request, exc: Exception, status: int, detail: str, message: str = "request failed"
) -> None:
    logger.warning(
        message,
        extra={
            "error_type": type(exc).__name__,
            "status_code": status,
            "path": request.url.path,
            "detail": detail,
            "request_id": _request_id(request),
        },
    )


async def _connector_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ConnectorError)
    # ``IdempotencyGuard`` converts CreatedButUnreadable itself (through the same builder); this
    # branch stays for routes outside the guard: the 202 must never degrade into a 5xx.
    if isinstance(exc, CreatedButUnreadable):
        return created_but_unreadable_response(request, exc)
    return connector_error_response(request, exc)


def error_status_and_code(exc: ConnectorError) -> tuple[int, str]:
    """HTTP status and ``error`` code for a domain error (shared with streaming exports)."""
    return next(
        ((s, c) for kind, s, c in _MAPPING if isinstance(exc, kind)), (502, "connector_error")
    )


def connector_error_response(request: Request, exc: ConnectorError) -> JSONResponse:
    """Map a domain error to its HTTP response (shared with ``IdempotencyGuard``)."""
    detail = scrub(str(exc), request.app.state.settings)
    if isinstance(exc, BatchPartiallyApplied):
        # 502, but part of the batch WAS applied: the ids must reach the client.
        _log_failure(request, exc, 502, detail)
        partial: dict[str, object] = {
            "error": "batch_partially_applied",
            "detail": detail,
            "created_ids": exc.created_ids,
            "failed_chunk": exc.failed_chunk,
        }
        return JSONResponse(partial, status_code=502)
    status, code = error_status_and_code(exc)
    _log_failure(request, exc, status, detail)
    return JSONResponse(_body(code, detail), status_code=status)


def created_but_unreadable_response(request: Request, exc: CreatedButUnreadable) -> JSONResponse:
    """Answer 202 Accepted: the record WAS created, only the read-back failed.

    201 would promise a body we cannot build, and any 4xx/5xx invites a blind retry that would
    duplicate the record. 202 plus the id (and a ``Location`` when the model has a resource
    path) tells the client the write happened and where to fetch it.
    """
    detail = scrub(str(exc), request.app.state.settings)
    _log_failure(request, exc, 202, detail, message="created but unreadable")
    headers: dict[str, str] = {}
    base = _RESOURCE_PATHS.get(exc.model)
    if base is not None:
        headers["Location"] = f"{base}/{exc.record_id}"
    body: dict[str, object] = {
        "error": "created_but_unreadable",
        "detail": detail,
        "id": exc.record_id,
        "model": exc.model,
    }
    return JSONResponse(body, status_code=202, headers=headers)


async def _api_key_error(request: Request, exc: Exception) -> JSONResponse:
    logger.warning("api key rejected", extra={"path": request.url.path})
    return JSONResponse(
        _body("unauthorized", "missing or invalid API key"),
        status_code=401,
        headers={"WWW-Authenticate": "ApiKey"},
    )


async def _request_validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    # Only location and message: pydantic's ``input`` would echo user-provided values.
    parts = [f"{'.'.join(str(p) for p in error['loc'])}: {error['msg']}" for error in exc.errors()]
    return JSONResponse(_body("validation_error", "; ".join(parts)), status_code=422)


async def _login_locked(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, LoginLocked)
    _log_failure(request, exc, 429, "login locked")
    return JSONResponse(
        _body("too_many_attempts", str(exc)),
        status_code=429,
        headers={"Retry-After": str(exc.retry_after_seconds)},
    )


async def _mapping_validation_failed(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, MappingValidationFailed)
    detail = scrub(str(exc), request.app.state.settings)
    _log_failure(request, exc, 422, detail)
    body: dict[str, object] = {
        "error": "validation_error",
        "detail": detail,
        "issues": [
            {"path": i.path, "severity": i.severity.value, "message": i.message} for i in exc.issues
        ],
    }
    return JSONResponse(body, status_code=422)


async def _unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    # Never echo the exception: it may carry paths, SQL or secrets. Details go to the log only.
    logger.error(
        "unhandled error",
        exc_info=exc,
        extra={"path": request.url.path, "request_id": _request_id(request)},
    )
    return JSONResponse(_body("internal_error", "internal server error"), status_code=500)


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ConnectorError, _connector_error)
    app.add_exception_handler(LoginLocked, _login_locked)
    app.add_exception_handler(MappingValidationFailed, _mapping_validation_failed)
    app.add_exception_handler(Exception, _unexpected_error)
    app.add_exception_handler(ApiKeyError, _api_key_error)
    app.add_exception_handler(RequestValidationError, _request_validation_error)
