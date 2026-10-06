"""Application factory.

Run with ``uvicorn conector_odoo.main:create_app --factory``.

Extension points for later tasks:

* ``_include_routers``: mount new routers here (the ``/webhooks/odoo`` router authenticates with
  its HMAC signature, so it must NOT declare ``require_api_key``).
* ``Idempotency-Key``: POST routes take ``GuardDep`` (``infrastructure/api/idempotency.py``) and
  wrap their action in ``guard.run(...)``; the SQLite store lives on ``Container.idempotency``
  (``Settings.idempotency_db_path``). The lifespan purges expired keys in a background task
  (``app.state.purge_task``) and closes each resource on shutdown, even if an earlier one fails.
"""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from conector_odoo.config import Settings, get_settings
from conector_odoo.infrastructure.api.dependencies import Container, build_container
from conector_odoo.infrastructure.api.errors import register_error_handlers
from conector_odoo.infrastructure.api.middleware import install_request_logging
from conector_odoo.infrastructure.api.routers import (
    customers,
    health,
    products,
    sale_orders,
    webhooks,
)
from conector_odoo.infrastructure.idempotency.purge import MultiPurger, purge_loop
from conector_odoo.infrastructure.migrations import open_admin_database
from conector_odoo.logging import configure_logging

logger = logging.getLogger(__name__)


def _include_routers(app: FastAPI) -> None:
    app.include_router(health.router)
    app.include_router(customers.router)
    app.include_router(products.router)
    app.include_router(sale_orders.router)
    app.include_router(webhooks.router)  # HMAC-authenticated: no require_api_key


async def _close_container(container: Container) -> None:
    """Release every container resource; one failure never prevents closing the rest."""
    try:
        await container.odoo_client.aclose()
    finally:
        try:
            await container.webhook_events.close()
        finally:
            await container.idempotency.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()
    configure_logging(resolved.log_level)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # its INFO lines carry full URLs

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if resolved.connector_api_key is None:
            logger.warning("connector API key not configured; data endpoints are unauthenticated")
        container = build_container(resolved)
        app.state.container = container
        try:
            admin_db = open_admin_database(resolved.admin_db_path)
        except BaseException:
            await _close_container(container)  # do not leak the stores built above
            raise
        app.state.admin_db = admin_db
        purge_task = asyncio.create_task(
            purge_loop(
                MultiPurger(container.idempotency, container.webhook_events),
                ttl_hours=resolved.idempotency_ttl_hours,
                interval_seconds=resolved.idempotency_purge_interval_seconds,
            ),
            name="idempotency-purge",
        )
        app.state.purge_task = purge_task
        try:
            yield
        finally:
            # each resource is released in its own try/finally so one failure cannot leak the rest
            try:
                purge_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await purge_task
            finally:
                try:
                    await _close_container(container)
                finally:
                    admin_db.close()

    app = FastAPI(title="conector-odoo", version="1.0.0", lifespan=lifespan)
    app.state.settings = resolved
    install_request_logging(app)
    register_error_handlers(app)
    _include_routers(app)
    return app
