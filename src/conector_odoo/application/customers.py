"""Customer use cases."""

from conector_odoo.domain.entities import Customer, CustomerData, CustomerQuery, CustomerUpdate
from conector_odoo.domain.errors import OdooNotFound, OdooValidationError
from conector_odoo.domain.ports import CustomerRepository

MAX_PAGE_SIZE = 1000


class CreateCustomer:
    def __init__(self, customers: CustomerRepository) -> None:
        self._customers = customers

    async def execute(self, data: CustomerData) -> Customer:
        if not data.name.strip():
            raise OdooValidationError("customer name must not be blank")
        return await self._customers.create(data)


class UpdateCustomer:
    def __init__(self, customers: CustomerRepository) -> None:
        self._customers = customers

    async def execute(self, customer_id: int, update: CustomerUpdate) -> Customer:
        if update.is_empty():
            raise OdooValidationError("update must change at least one field")
        if update.name is not None and not update.name.strip():
            raise OdooValidationError("customer name must not be blank")
        return await self._customers.update(customer_id, update)


class GetCustomer:
    def __init__(self, customers: CustomerRepository) -> None:
        self._customers = customers

    async def execute(self, customer_id: int) -> Customer:
        customer = await self._customers.get(customer_id)
        if customer is None:
            raise OdooNotFound(f"customer {customer_id} not found")
        return customer


class SearchCustomers:
    def __init__(self, customers: CustomerRepository) -> None:
        self._customers = customers

    async def execute(self, query: CustomerQuery) -> list[Customer]:
        if not 1 <= query.limit <= MAX_PAGE_SIZE:
            raise OdooValidationError(f"limit must be between 1 and {MAX_PAGE_SIZE}")
        if query.offset < 0:
            raise OdooValidationError("offset must not be negative")
        return await self._customers.search(query)
