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

    async def find_by_emails(self, emails: list[str]) -> dict[str, Customer]:
        """Find existing customers by email in a few batched lookups (never one per email).

        Matching is case-insensitive and exact. Keys of the result are the lowercased emails;
        when several customers share an email the first one (lowest id) wins.
        """
        ...

    async def create_many(self, data: list[CustomerData]) -> list[int]:
        """Create customers in chunks; returns the new ids in input order.

        Raises ``BatchPartiallyApplied`` (carrying the ids created so far) when a later chunk
        fails.
        """
        ...

    async def apply_update(self, customer_id: int, update: CustomerUpdate) -> None:
        """Write only the provided fields, without reading the record back."""
        ...

    async def known_country_codes(self, codes: set[str]) -> set[str]:
        """Return the subset of ISO country ``codes`` that exist (one batched lookup)."""
        ...

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
