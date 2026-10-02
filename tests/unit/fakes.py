"""In-memory fake repositories shared by unit tests."""

from dataclasses import replace

from conector_odoo.domain.entities import (
    Customer,
    CustomerData,
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

    async def archive(self, customer_id: int) -> None:
        current = self.items.get(customer_id)
        if current is None:
            raise OdooNotFound(f"customer {customer_id} not found")
        self.items[customer_id] = replace(current, active=False)


class FakeProductRepository:
    def __init__(self, products: list[Product] | None = None) -> None:
        self.items = {p.id: p for p in products or []}

    async def get(self, product_id: int) -> Product | None:
        return self.items.get(product_id)

    async def list(self, limit: int, offset: int) -> list[Product]:
        return list(self.items.values())[offset : offset + limit]


class FakeSaleOrderRepository:
    def __init__(self) -> None:
        self.items: dict[int, SaleOrder] = {}
        self._next_id = 1
        self.confirm_calls = 0

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

    async def confirm(self, order_id: int) -> SaleOrder:
        self.confirm_calls += 1
        order = self.items.get(order_id)
        if order is None:
            raise OdooNotFound(f"sale order {order_id} not found")
        confirmed = replace(order, state="sale")
        self.items[order_id] = confirmed
        return confirmed

    async def get(self, order_id: int) -> SaleOrder | None:
        return self.items.get(order_id)
