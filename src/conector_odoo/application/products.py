"""Product use cases (read-only)."""

from conector_odoo.application.customers import MAX_PAGE_SIZE
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
