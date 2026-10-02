"""Customer use cases."""

from collections.abc import AsyncIterator

from conector_odoo.application.pagination import MAX_PAGE_SIZE, validate_batch_size
from conector_odoo.domain.entities import (
    Customer,
    CustomerData,
    CustomerFilter,
    CustomerQuery,
    CustomerUpdate,
)
from conector_odoo.domain.errors import OdooNotFound, OdooValidationError
from conector_odoo.domain.ports import CustomerRepository


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


class ExportCustomers:
    """Stream all matching customers as batches (bounded memory, for exports)."""

    def __init__(self, customers: CustomerRepository) -> None:
        self._customers = customers

    def execute(
        self, filters: CustomerFilter, batch_size: int | None = None
    ) -> AsyncIterator[list[Customer]]:
        validate_batch_size(batch_size)  # eager: fails before any streaming starts
        return self._customers.iter_batches(filters, batch_size)
