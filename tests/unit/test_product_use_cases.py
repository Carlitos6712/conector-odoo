import pytest

from conector_odoo.application.products import GetProduct, ListProducts
from conector_odoo.domain.entities import Product
from conector_odoo.domain.errors import OdooNotFound, OdooValidationError
from tests.unit.fakes import FakeProductRepository

PRODUCTS = [Product(id=i, name=f"P{i}") for i in range(1, 6)]


async def test_get_product_returns_the_product() -> None:
    assert await GetProduct(FakeProductRepository(PRODUCTS)).execute(2) == PRODUCTS[1]


async def test_get_product_raises_not_found_when_missing() -> None:
    with pytest.raises(OdooNotFound):
        await GetProduct(FakeProductRepository(PRODUCTS)).execute(99)


async def test_list_products_pages() -> None:
    result = await ListProducts(FakeProductRepository(PRODUCTS)).execute(limit=2, offset=1)
    assert [p.id for p in result] == [2, 3]


@pytest.mark.parametrize(("limit", "offset"), [(0, 0), (1001, 0), (10, -1)])
async def test_list_products_rejects_bad_paging(limit: int, offset: int) -> None:
    with pytest.raises(OdooValidationError):
        await ListProducts(FakeProductRepository(PRODUCTS)).execute(limit=limit, offset=offset)
