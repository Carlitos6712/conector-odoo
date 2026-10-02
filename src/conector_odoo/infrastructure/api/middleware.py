"""Request logging middleware with a request id (``X-Request-ID`` echoed or generated)."""

import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response

logger = logging.getLogger("conector_odoo.request")
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def _request_id(request: Request) -> str:
    candidate = request.headers.get("x-request-id", "")
    return candidate if _SAFE_ID.match(candidate) else uuid.uuid4().hex


def install_request_logging(app: FastAPI) -> None:
    @app.middleware("http")
    async def log_requests(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = _request_id(request)
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            # Only method, path and status: headers (API keys) and bodies are never logged.
            logger.info(
                "request",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": status,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
