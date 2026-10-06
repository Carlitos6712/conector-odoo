"""Application factory.

Run with ``uvicorn conector_odoo.main:create_app --factory``.

Extension points for later tasks:

* ``_include_routers``: mount new routers here (the ``/webhooks/odoo`` router authenticates with
  its HMAC signature, so it must NOT declare ``require_api_key``).
* ``/admin/api``: add routers in ``infrastructure/admin_api/router.py`` (they land behind the
  session/role/CSRF guard by default); services are built in ``admin_api/services.py``.
* ``Idempotency-Key``: POST routes take ``GuardDep`` (``infrastructure/api/idempotency.py``) and
  wrap their action in ``guard.run(...)``; the SQLite store lives on ``Container.idempotency``
  (``Settings.idempotency_db_path``). The lifespan purges expired keys in a background task
  (``app.state.purge_task``) and closes each resource on shutdown, even if an earlier one fails.
"""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI

from conector_odoo.application.webhook_triggers import register_webhook_triggers
from conector_odoo.config import Settings, get_settings
from conector_odoo.infrastructure.admin_api.router import include_admin_api
from conector_odoo.infrastructure.admin_api.services import (
    bootstrap_first_admin,
    build_admin_services,
)
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
from conector_odoo.infrastructure.api.static_frontend import mount_frontend
from conector_odoo.infrastructure.idempotency.purge import MultiPurger, purge_loop
from conector_odoo.infrastructure.migrations import close_admin_database, open_admin_database
from conector_odoo.infrastructure.profiles.rotation import check_vault_at_startup
from conector_odoo.infrastructure.profiles.vault import build_vault
from conector_odoo.logging import configure_logging

logger = logging.getLogger(__name__)


def _include_routers(app: FastAPI) -> None:
    app.include_router(health.router)
    app.include_router(customers.router)
    app.include_router(products.router)
    app.include_router(sale_orders.router)
    app.include_router(webhooks.router)  # HMAC-authenticated: no require_api_key
    include_admin_api(app)  # session-cookie authenticated: no require_api_key


async def _cancel_task(task: "asyncio.Task[None]") -> None:
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


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
        # Every resource registers its closer the moment it exists, so a failure at any later
        # startup step (or any closer failing at shutdown) still releases everything else.
        async with AsyncExitStack() as stack:
            container = build_container(resolved)
            stack.push_async_callback(_close_container, container)
            app.state.container = container
            admin_db = open_admin_database(resolved.admin_db_path)
            stack.callback(close_admin_database, admin_db)
            app.state.admin_db = admin_db
            check_vault_at_startup(admin_db, build_vault(resolved))
            admin = build_admin_services(resolved, admin_db)
            app.state.admin = admin
            # Closed before the admin database (background runs write to it) and after the
            # scheduler has stopped starting new ones.
            stack.push_async_callback(admin.aclose)
            await bootstrap_first_admin(resolved, admin)
            register_webhook_triggers(container.event_bus, admin.webhook_trigger)
            purge_task = asyncio.create_task(
                purge_loop(
                    MultiPurger(container.idempotency, container.webhook_events),
                    ttl_hours=resolved.idempotency_ttl_hours,
                    interval_seconds=resolved.idempotency_purge_interval_seconds,
                ),
                name="idempotency-purge",
            )
            stack.push_async_callback(_cancel_task, purge_task)
            app.state.purge_task = purge_task
            if resolved.sync_scheduler_enabled:
                admin.scheduler.start()
                stack.push_async_callback(admin.scheduler.stop)
            yield

    app = FastAPI(title="conector-odoo", version="1.0.0", lifespan=lifespan)
    app.state.settings = resolved
    install_request_logging(app)
    register_error_handlers(app)
    _include_routers(app)
    mount_frontend(app, resolved.frontend_dist_dir)  # last: it must never shadow a real route
    return app
