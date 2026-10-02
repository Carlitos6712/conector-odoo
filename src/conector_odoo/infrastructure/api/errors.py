"""Exception handlers: domain errors -> HTTP status and an ``ErrorOut`` JSON body."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from conector_odoo.config import Settings
from conector_odoo.domain.errors import (
    ConnectorError,
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


def scrub(text: str, settings: Settings) -> str:
    """Mask configured secrets in a message before it leaves the process."""
    secrets = [settings.odoo_api_key, settings.webhook_secret, settings.connector_api_key]
    for secret in secrets:
        if secret is not None and secret.get_secret_value():
            text = text.replace(secret.get_secret_value(), "***")
    return text


def _body(error: str, detail: str) -> dict[str, str]:
    return {"error": error, "detail": detail}


async def _connector_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ConnectorError)
    status, code = next(
        ((s, c) for kind, s, c in _MAPPING if isinstance(exc, kind)), (502, "connector_error")
    )
    detail = scrub(str(exc), request.app.state.settings)
    logger.warning(
        "request failed",
        extra={"error_type": type(exc).__name__, "status_code": status, "path": request.url.path},
    )
    return JSONResponse(_body(code, detail), status_code=status)


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
