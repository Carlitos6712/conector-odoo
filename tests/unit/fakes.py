"""In-memory fake repositories shared by unit tests."""

from collections.abc import AsyncIterator
from dataclasses import replace

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
from conector_odoo.domain.errors import OdooNotFound


class FakeCustomerRepository:
    def __init__(self) -> None:
        self.items: dict[int, Customer] = {}
        self._next_id = 1
        self.calls: list[str] = []
        self.export_calls: list[tuple[CustomerFilter, int | None]] = []
        self.export_error: BaseException | None = None
        self.export_error_after = 1  # batches delivered before ``export_error`` is raised

    async def create(self, data: CustomerData) -> Customer:
        self.calls.append("create")
        customer = Customer(
            id=self._next_id,
            name=data.name,
            email=data.email,
            phone=data.phone,
            street=data.street,
            city=data.city,
            zip=data.zip,
            country_code=data.country_code,
            vat=data.vat,
            is_company=data.is_company,
            active=True,
        )
        self.items[self._next_id] = customer
        self._next_id += 1
        return customer

    async def update(self, customer_id: int, update: CustomerUpdate) -> Customer:
        self.calls.append("update")
        current = self.items.get(customer_id)
        if current is None:
            raise OdooNotFound(f"customer {customer_id} not found")
        updated = replace(current, **update.changes())
        self.items[customer_id] = updated
        return updated

    async def get(self, customer_id: int) -> Customer | None:
        return self.items.get(customer_id)

    async def search(self, query: CustomerQuery) -> list[Customer]:
        found = [
            c
            for c in self.items.values()
            if (query.email is None or c.email == query.email)
            and (query.name is None or query.name.lower() in c.name.lower())
        ]
        return found[query.offset : query.offset + query.limit]

    async def iter_batches(
        self, filters: CustomerFilter, batch_size: int | None = None
    ) -> AsyncIterator[list[Customer]]:
        self.export_calls.append((filters, batch_size))
        rows = [
            c
            for c in self.items.values()
            if (filters.email is None or c.email == filters.email)
            and (filters.name is None or filters.name.lower() in c.name.lower())
            and (filters.active is None or c.active == filters.active)
        ]
        size = batch_size or 2
        sent = 0
        for start in range(0, len(rows), size):
            if self.export_error is not None and sent >= self.export_error_after:
                raise self.export_error
            yield rows[start : start + size]
            sent += 1
        if self.export_error is not None and sent <= self.export_error_after:
            raise self.export_error

    async def archive(self, customer_id: int) -> None:
        current = self.items.get(customer_id)
        if current is None:
            raise OdooNotFound(f"customer {customer_id} not found")
        self.items[customer_id] = replace(current, active=False)


class FakeProductRepository:
    def __init__(self, products: list[Product] | None = None) -> None:
        self.items = {p.id: p for p in products or []}
        self.export_calls: list[int | None] = []
        self.export_error: BaseException | None = None
        self.export_error_after = 1

    async def get(self, product_id: int) -> Product | None:
        return self.items.get(product_id)

    # Before ``list``: that method name shadows the builtin inside the class body.
    async def iter_batches(self, batch_size: int | None = None) -> AsyncIterator[list[Product]]:
        self.export_calls.append(batch_size)
        rows = list(self.items.values())
        size = batch_size or 2
        sent = 0
        for start in range(0, len(rows), size):
            if self.export_error is not None and sent >= self.export_error_after:
                raise self.export_error
            yield rows[start : start + size]
            sent += 1
        if self.export_error is not None and sent <= self.export_error_after:
            raise self.export_error

    async def list(self, limit: int, offset: int) -> list[Product]:
        return list(self.items.values())[offset : offset + limit]


class FakeSaleOrderRepository:
    def __init__(self) -> None:
        self.items: dict[int, SaleOrder] = {}
        self._next_id = 1
        self.confirm_calls = 0
        self.get_companies: list[int | None] = []
        self.confirm_companies: list[int | None] = []

    async def create(self, data: SaleOrderData) -> SaleOrder:
        order = SaleOrder(
            id=self._next_id,
            customer_id=data.customer_id,
            lines=data.lines,
            state="draft",
            name=f"S{self._next_id:05d}",
            amount_total=0.0,
            company_id=data.company_id,
        )
        self.items[self._next_id] = order
        self._next_id += 1
        return order

    async def confirm(self, order_id: int, company_id: int | None = None) -> SaleOrder:
        self.confirm_calls += 1
        self.confirm_companies.append(company_id)
        order = self.items.get(order_id)
        if order is None:
            raise OdooNotFound(f"sale order {order_id} not found")
        confirmed = replace(order, state="sale")
        self.items[order_id] = confirmed
        return confirmed

    async def get(self, order_id: int, company_id: int | None = None) -> SaleOrder | None:
        self.get_companies.append(company_id)
        return self.items.get(order_id)
