"""Optional ``X-API-Key`` protection for the connector's own endpoints.

When ``Settings.connector_api_key`` is set, every router that declares ``require_api_key`` as a
dependency demands a matching header (constant-time comparison). ``/health`` stays public so
orchestrators and load balancers can probe it without a secret; the webhook router (T7) is
authenticated by its HMAC signature instead and does not use this dependency.
"""

import hmac
from typing import Annotated

from fastapi import Depends, Header

from conector_odoo.config import Settings
from conector_odoo.infrastructure.api.dependencies import get_settings


class ApiKeyError(Exception):
    """Missing or invalid ``X-API-Key``; mapped to HTTP 401 by the error handlers."""


async def require_api_key(
    settings: Annotated[Settings, Depends(get_settings)],
    x_api_key: Annotated[str | None, Header()] = None,
) -> None:
    expected = settings.connector_api_key
    if expected is None:
        return
    provided = (x_api_key or "").encode()
    if not hmac.compare_digest(provided, expected.get_secret_value().encode()):
        raise ApiKeyError("missing or invalid API key")
