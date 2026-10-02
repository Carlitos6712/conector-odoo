"""Exception handlers: domain errors -> HTTP status and an ``ErrorOut`` JSON body."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from conector_odoo.config import Settings
from conector_odoo.domain.errors import (
    BatchPartiallyApplied,
    ConnectorError,
    CreatedButUnreadable,
    OdooAuthError,
    OdooNotFound,
    OdooPermissionError,
    OdooUnavailable,
    OdooValidationError,
)
from conector_odoo.infrastructure.api.security import ApiKeyError

logger = logging.getLogger(__name__)

# (status, error code); the first matching entry wins, ``ConnectorError`` is the fallback.
_MAPPING: tuple[tuple[type[ConnectorError], int, str], ...] = (
    (OdooAuthError, 401, "odoo_auth_error"),
    (OdooPermissionError, 403, "permission_denied"),
    (OdooNotFound, 404, "not_found"),
    (OdooValidationError, 422, "validation_error"),
    (OdooUnavailable, 502, "odoo_unavailable"),
)


# Where a freshly created record can be fetched, by Odoo model (used for the 202 ``Location``).
_RESOURCE_PATHS = {"res.partner": "/customers", "sale.order": "/sale-orders"}


def scrub(text: str, settings: Settings) -> str:
    """Mask every configured secret in a message before it leaves the process.

    Settings enforce a minimum secret length, so masking every non-empty value cannot mangle
    ordinary text; a short secret that leaked would be worse than a mangled message.
    """
    secrets = [settings.odoo_api_key, settings.webhook_secret, settings.connector_api_key]
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
    status, code = next(
        ((s, c) for kind, s, c in _MAPPING if isinstance(exc, kind)), (502, "connector_error")
    )
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


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ConnectorError, _connector_error)
    app.add_exception_handler(ApiKeyError, _api_key_error)
    app.add_exception_handler(RequestValidationError, _request_validation_error)
