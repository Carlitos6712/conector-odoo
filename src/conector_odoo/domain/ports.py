"""Ports (async Protocols) implemented by infrastructure adapters."""

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Protocol

from conector_odoo.domain.entities import (
    Customer,
    CustomerData,
    CustomerFilter,
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

    def iter_batches(
        self, filters: CustomerFilter, batch_size: int | None = None
    ) -> AsyncIterator[list[Customer]]:
        """Stream every matching customer in id order, ``batch_size`` at a time.

        ``batch_size=None`` leaves the choice to the adapter. Only one batch is held in memory.
        """
        ...


class ProductRepository(Protocol):
    async def get(self, product_id: int) -> Product | None: ...

    # Declared before ``list``: inside this class body the name ``list`` would otherwise shadow
    # the builtin in later annotations.
    def iter_batches(self, batch_size: int | None = None) -> AsyncIterator[list[Product]]:
        """Stream every sellable product in id order, ``batch_size`` at a time."""
        ...

    async def list(self, limit: int, offset: int) -> list[Product]: ...


class SaleOrderRepository(Protocol):
    async def create(self, data: SaleOrderData) -> SaleOrder: ...

    async def confirm(self, order_id: int, company_id: int | None = None) -> SaleOrder: ...

    async def get(self, order_id: int, company_id: int | None = None) -> SaleOrder | None: ...


class EventBus(Protocol):
    def subscribe(self, event_type: str, handler: EventHandler) -> None: ...

    async def publish(self, event: OdooEvent) -> bool:
        """Deliver the event to its handlers; ``True`` when every handler succeeded."""
        ...
