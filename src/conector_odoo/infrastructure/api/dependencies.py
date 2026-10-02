"""Dependency wiring.

``build_container`` creates the infrastructure once (in the app lifespan) and stores it on
``app.state.container``. Repository dependencies read from it; use-case dependencies are built
from the repositories. Tests override the repository dependencies (and ``get_odoo_client`` for
``/health``) through ``app.dependency_overrides``.
"""

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
from conector_odoo.domain.ports import CustomerRepository, ProductRepository, SaleOrderRepository
from conector_odoo.infrastructure.idempotency.sqlite_store import SqliteIdempotencyStore
from conector_odoo.infrastructure.idempotency.store import IdempotencyStore
from conector_odoo.infrastructure.odoo.client import OdooClient
from conector_odoo.infrastructure.odoo.customer_repository import OdooCustomerRepository
from conector_odoo.infrastructure.odoo.factory import build_odoo_client
from conector_odoo.infrastructure.odoo.product_repository import OdooProductRepository
from conector_odoo.infrastructure.odoo.sale_order_repository import OdooSaleOrderRepository
from conector_odoo.infrastructure.webhooks.handlers import register_default_handlers
from conector_odoo.infrastructure.webhooks.store import SqliteWebhookEventStore


@dataclass(frozen=True)
class Container:
    odoo_client: OdooClient
    customers: CustomerRepository
    products: ProductRepository
    orders: SaleOrderRepository
    idempotency: IdempotencyStore
    event_bus: InMemoryEventBus
    webhook_events: SqliteWebhookEventStore


def build_container(settings: Settings) -> Container:
    client = build_odoo_client(settings)
    event_bus = InMemoryEventBus()
    register_default_handlers(event_bus)
    return Container(
        odoo_client=client,
        customers=OdooCustomerRepository(client, batch_size=settings.odoo_batch_size),
        products=OdooProductRepository(client, batch_size=settings.odoo_batch_size),
        orders=OdooSaleOrderRepository(client),
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


def get_odoo_client(container: ContainerDep) -> OdooClient:
    return container.odoo_client


def get_customer_repository(container: ContainerDep) -> CustomerRepository:
    return container.customers


def get_product_repository(container: ContainerDep) -> ProductRepository:
    return container.products


def get_sale_order_repository(container: ContainerDep) -> SaleOrderRepository:
    return container.orders


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
