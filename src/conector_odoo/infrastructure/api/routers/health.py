"""``GET /health`` and ``GET /livez``: public on purpose (no ``X-API-Key``), no secret needed."""

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from conector_odoo.config import Settings
from conector_odoo.domain.errors import ConnectorError
from conector_odoo.infrastructure.api.dependencies import get_odoo_client, get_settings
from conector_odoo.infrastructure.api.errors import scrub
from conector_odoo.infrastructure.api.schemas import DegradedHealthOut, HealthOut
from conector_odoo.infrastructure.odoo.client import OdooClient

router = APIRouter(tags=["health"])


@router.get("/livez")
async def livez() -> dict[str, str]:
    """Process liveness only: never touches Odoo, so it is the container healthcheck."""
    return {"status": "ok"}


@router.get("/health", response_model=HealthOut, responses={503: {"model": DegradedHealthOut}})
async def health(
    client: Annotated[OdooClient, Depends(get_odoo_client)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> HealthOut | JSONResponse:
    try:
        result = await client.check()
    except ConnectorError as exc:
        return JSONResponse(
            {"status": "degraded", "detail": scrub(str(exc), settings)}, status_code=503
        )
    return HealthOut(
        status="ok", odoo="reachable", uid=result.get("uid"), protocol=settings.odoo_protocol
    )
