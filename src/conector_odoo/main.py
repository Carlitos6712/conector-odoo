"""Application factory.

Run with ``uvicorn conector_odoo.main:create_app --factory``.

Extension points for later tasks:

* ``_include_routers``: mount new routers here (the T7 ``/webhooks/odoo`` router authenticates
  with its HMAC signature, so it must NOT declare ``require_api_key``).
* T6 ``Idempotency-Key``: add a dependency (or route-level middleware) next to ``require_api_key``
  on the POST routes of ``routers/customers.py`` and ``routers/sale_orders.py``;
  ``Settings.idempotency_db_path`` already holds the SQLite location.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from conector_odoo.config import Settings, get_settings
from conector_odoo.infrastructure.api.dependencies import build_container
from conector_odoo.infrastructure.api.errors import register_error_handlers
from conector_odoo.infrastructure.api.middleware import install_request_logging
from conector_odoo.infrastructure.api.routers import customers, health, products, sale_orders
from conector_odoo.logging import configure_logging


def _include_routers(app: FastAPI) -> None:
    app.include_router(health.router)
    app.include_router(customers.router)
    app.include_router(products.router)
    app.include_router(sale_orders.router)


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()
    configure_logging(resolved.log_level)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # its INFO lines carry full URLs

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        container = build_container(resolved)
        app.state.container = container
        try:
            yield
        finally:
            await container.odoo_client.aclose()

    app = FastAPI(title="conector-odoo", version="1.0.0", lifespan=lifespan)
    app.state.settings = resolved
    install_request_logging(app)
    register_error_handlers(app)
    _include_routers(app)
    return app
