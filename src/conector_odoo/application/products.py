"""Product use cases (read-only)."""

from collections.abc import AsyncIterator

from conector_odoo.application.pagination import MAX_PAGE_SIZE, validate_batch_size
from conector_odoo.domain.entities import Product
from conector_odoo.domain.errors import OdooNotFound, OdooValidationError
from conector_odoo.domain.ports import ProductRepository


class GetProduct:
    def __init__(self, products: ProductRepository) -> None:
        self._products = products

    async def execute(self, product_id: int) -> Product:
        product = await self._products.get(product_id)
        if product is None:
            raise OdooNotFound(f"product {product_id} not found")
        return product


class ListProducts:
    def __init__(self, products: ProductRepository) -> None:
        self._products = products

    async def execute(self, limit: int = 50, offset: int = 0) -> list[Product]:
        if not 1 <= limit <= MAX_PAGE_SIZE:
            raise OdooValidationError(f"limit must be between 1 and {MAX_PAGE_SIZE}")
        if offset < 0:
            raise OdooValidationError("offset must not be negative")
        return await self._products.list(limit, offset)


class ExportProducts:
    """Stream all sellable products as batches (bounded memory, for exports)."""

    def __init__(self, products: ProductRepository) -> None:
        self._products = products

    def execute(self, batch_size: int | None = None) -> AsyncIterator[list[Product]]:
        validate_batch_size(batch_size)  # eager: fails before any streaming starts
        return self._products.iter_batches(batch_size)
