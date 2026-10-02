import pytest

from conector_odoo.domain.entities import Product
from conector_odoo.domain.errors import OdooNotFound
from conector_odoo.infrastructure.odoo.product_repository import OdooProductRepository
from tests.adapters.fake_odoo_client import FakeOdooClient

FIELDS = ["name", "default_code", "lst_price", "uom_id", "active"]


def row(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "id": 3,
        "name": "Desk",
        "default_code": "D-1",
        "lst_price": 99.5,
        "uom_id": [1, "Units"],
        "active": True,
    }
    data.update(overrides)
    return data


@pytest.fixture
def client() -> FakeOdooClient:
    return FakeOdooClient()


@pytest.fixture
def repo(client: FakeOdooClient) -> OdooProductRepository:
    return OdooProductRepository(client)  # type: ignore[arg-type]


async def test_get_maps_product(repo: OdooProductRepository, client: FakeOdooClient) -> None:
    client.script("product.product", "read", [row()])
    assert await repo.get(3) == Product(
        id=3, name="Desk", default_code="D-1", list_price=99.5, uom_name="Units", active=True
    )
    assert client.calls_to("product.product", "read")[0] == {"ids": [3], "fields": FIELDS}


async def test_get_maps_false_values(repo: OdooProductRepository, client: FakeOdooClient) -> None:
    client.script("product.product", "read", [row(default_code=False, uom_id=False)])
    product = await repo.get(3)
    assert product is not None
    assert product.default_code is None
    assert product.uom_name is None


@pytest.mark.parametrize("result", [[], OdooNotFound("gone")])
async def test_get_returns_none_when_missing(
    repo: OdooProductRepository, client: FakeOdooClient, result: object
) -> None:
    client.script("product.product", "read", result)
    assert await repo.get(3) is None


async def test_list_filters_sellable_and_pages(
    repo: OdooProductRepository, client: FakeOdooClient
) -> None:
    client.script("product.product", "search_read", [row(), row(id=4)])
    products = await repo.list(limit=2, offset=4)
    assert [p.id for p in products] == [3, 4]
    call = client.calls_to("product.product", "search_read")[0]
    assert call["domain"] == [["sale_ok", "=", True]]
    assert (call["limit"], call["offset"], call["order"]) == (2, 4, "id asc")
    assert call["fields"] == FIELDS
