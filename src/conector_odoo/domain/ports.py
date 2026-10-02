"""Ports (async Protocols) implemented by infrastructure adapters."""

from collections.abc import Awaitable, Callable
from typing import Protocol

from conector_odoo.domain.entities import (
    Customer,
    CustomerData,
    CustomerQuery,
    CustomerUpdate,
    Product,
    SaleOrder,
    SaleOrderData,
)
from conector_odoo.domain.events import OdooEvent

EventHandler = Callable[[OdooEvent], Awaitable[None]]


class CustomerRepository(Protocol):
    async def create(self, data: CustomerData) -> Customer: ...

    async def update(self, customer_id: int, update: CustomerUpdate) -> Customer: ...

    async def get(self, customer_id: int) -> Customer | None: ...

    async def search(self, query: CustomerQuery) -> list[Customer]: ...

    async def archive(self, customer_id: int) -> None: ...


class ProductRepository(Protocol):
    async def get(self, product_id: int) -> Product | None: ...

    async def list(self, limit: int, offset: int) -> list[Product]: ...


class SaleOrderRepository(Protocol):
    async def create(self, data: SaleOrderData) -> SaleOrder: ...

    async def confirm(self, order_id: int, company_id: int | None = None) -> SaleOrder: ...

    async def get(self, order_id: int, company_id: int | None = None) -> SaleOrder | None: ...


class EventBus(Protocol):
    def subscribe(self, event_type: str, handler: EventHandler) -> None: ...

    async def publish(self, event: OdooEvent) -> None: ...
