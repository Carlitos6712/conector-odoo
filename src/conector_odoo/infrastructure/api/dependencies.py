"""Dependency wiring.

``build_container`` creates the infrastructure once (in the app lifespan) and stores it on
``app.state.container``. Repository dependencies lease the current Odoo connection from
``container.odoo`` per request (it can be swapped at runtime); use-case dependencies are built
from the repositories. Tests override the repository dependencies (and ``get_odoo_client`` for
``/health``) through ``app.dependency_overrides``.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from conector_odoo.application.customers import (
    BulkUpsertCustomers,
    CreateCustomer,
    ExportCustomers,
    GetCustomer,
    SearchCustomers,
    UpdateCustomer,
)
from conector_odoo.application.event_bus import InMemoryEventBus
from conector_odoo.application.products import ExportProducts, GetProduct, ListProducts
from conector_odoo.application.sale_orders import ConfirmSaleOrder, CreateSaleOrder, GetSaleOrder
from conector_odoo.config import Settings
from conector_odoo.domain.errors import OdooNotConfigured
from conector_odoo.domain.ports import CustomerRepository, ProductRepository, SaleOrderRepository
from conector_odoo.infrastructure.idempotency.sqlite_store import SqliteIdempotencyStore
from conector_odoo.infrastructure.idempotency.store import IdempotencyStore
from conector_odoo.infrastructure.odoo.client import OdooClient
from conector_odoo.infrastructure.odoo.provider import OdooConnectionProvider, OdooLease
from conector_odoo.infrastructure.webhooks.handlers import register_default_handlers
from conector_odoo.infrastructure.webhooks.store import SqliteWebhookEventStore


@dataclass(frozen=True)
class Container:
    """``odoo`` is the swappable Odoo connection: empty until the lifespan resolves it (active
    profile > env > none), so the app starts with no Odoo configured at all."""

    odoo: OdooConnectionProvider
    idempotency: IdempotencyStore
    event_bus: InMemoryEventBus
    webhook_events: SqliteWebhookEventStore

    @property
    def odoo_client(self) -> OdooClient:
        """The current client (kept for callers that predate the provider); raises when none."""
        current = self.odoo.current
        if current is None:
            raise OdooNotConfigured("no Odoo connection is configured")
        return current.client


def build_container(settings: Settings) -> Container:
    event_bus = InMemoryEventBus()
    register_default_handlers(event_bus)
    return Container(
        odoo=OdooConnectionProvider(settings),
        idempotency=SqliteIdempotencyStore(
            settings.idempotency_db_path,
            in_progress_timeout_seconds=settings.idempotency_in_progress_timeout_seconds,
        ),
        event_bus=event_bus,
        webhook_events=SqliteWebhookEventStore(settings.idempotency_db_path),
    )


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


ContainerDep = Annotated[Container, Depends(get_container)]


def get_event_bus(container: ContainerDep) -> InMemoryEventBus:
    return container.event_bus


def get_webhook_event_store(container: ContainerDep) -> SqliteWebhookEventStore:
    return container.webhook_events


async def get_odoo_lease(container: ContainerDep) -> AsyncIterator[OdooLease]:
    """Pin the current Odoo connection for the whole request (including a streamed response), so
    a runtime switch never closes a client a request is still using. Raises ``OdooNotConfigured``
    (503) when there is none."""
    lease = container.odoo.acquire()
    try:
        yield lease
    finally:
        lease.release()


OdooLeaseDep = Annotated[OdooLease, Depends(get_odoo_lease)]


async def get_odoo_client(container: ContainerDep) -> AsyncIterator[OdooClient | None]:
    """The current client for ``/health`` (``None`` when no connection is configured)."""
    lease = container.odoo.try_acquire()
    try:
        yield None if lease is None else lease.client
    finally:
        if lease is not None:
            lease.release()


def get_customer_repository(lease: OdooLeaseDep) -> CustomerRepository:
    return lease.connection.customers


def get_product_repository(lease: OdooLeaseDep) -> ProductRepository:
    return lease.connection.products


def get_sale_order_repository(lease: OdooLeaseDep) -> SaleOrderRepository:
    return lease.connection.orders


CustomerRepo = Annotated[CustomerRepository, Depends(get_customer_repository)]
ProductRepo = Annotated[ProductRepository, Depends(get_product_repository)]
SaleOrderRepo = Annotated[SaleOrderRepository, Depends(get_sale_order_repository)]


def get_create_customer(repo: CustomerRepo) -> CreateCustomer:
    return CreateCustomer(repo)


def get_update_customer(repo: CustomerRepo) -> UpdateCustomer:
    return UpdateCustomer(repo)


def get_get_customer(repo: CustomerRepo) -> GetCustomer:
    return GetCustomer(repo)


def get_search_customers(repo: CustomerRepo) -> SearchCustomers:
    return SearchCustomers(repo)


def get_export_customers(repo: CustomerRepo) -> ExportCustomers:
    return ExportCustomers(repo)


def get_bulk_upsert_customers(repo: CustomerRepo) -> BulkUpsertCustomers:
    return BulkUpsertCustomers(repo)


def get_export_products(repo: ProductRepo) -> ExportProducts:
    return ExportProducts(repo)


def get_get_product(repo: ProductRepo) -> GetProduct:
    return GetProduct(repo)


def get_list_products(repo: ProductRepo) -> ListProducts:
    return ListProducts(repo)


def get_create_sale_order(repo: SaleOrderRepo) -> CreateSaleOrder:
    return CreateSaleOrder(repo)


def get_confirm_sale_order(repo: SaleOrderRepo) -> ConfirmSaleOrder:
    return ConfirmSaleOrder(repo)


def get_get_sale_order(repo: SaleOrderRepo) -> GetSaleOrder:
    return GetSaleOrder(repo)
