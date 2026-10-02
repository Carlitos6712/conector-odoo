import pytest

from conector_odoo.domain.entities import SaleOrder, SaleOrderData, SaleOrderLine
from conector_odoo.domain.errors import OdooNotFound
from conector_odoo.infrastructure.odoo.sale_order_repository import OdooSaleOrderRepository
from tests.adapters.fake_odoo_client import FakeOdooClient

ORDER_FIELDS = ["partner_id", "order_line", "state", "name", "amount_total", "company_id"]
LINE_FIELDS = ["product_id", "product_uom_qty", "price_unit"]


def order_row(state: str = "draft", **overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": 8,
        "partner_id": [5, "Ada"],
        "order_line": [11, 12],
        "state": state,
        "name": "S00008",
        "amount_total": 120.0,
        "company_id": [2, "Acme"],
    }
    row.update(overrides)
    return row


LINES = [
    {"id": 11, "product_id": [3, "Desk"], "product_uom_qty": 2.0, "price_unit": 50.0},
    {"id": 12, "product_id": [4, "Lamp"], "product_uom_qty": 1.0, "price_unit": 20.0},
]


@pytest.fixture
def client() -> FakeOdooClient:
    return FakeOdooClient()


@pytest.fixture
def repo(client: FakeOdooClient) -> OdooSaleOrderRepository:
    return OdooSaleOrderRepository(client)  # type: ignore[arg-type]


def script_get(client: FakeOdooClient, state: str = "draft", **overrides: object) -> None:
    client.script("sale.order", "read", [order_row(state, **overrides)])
    client.script("sale.order.line", "read", LINES)


async def test_get_reads_order_and_lines(
    repo: OdooSaleOrderRepository, client: FakeOdooClient
) -> None:
    script_get(client)
    assert await repo.get(8) == SaleOrder(
        id=8,
        customer_id=5,
        lines=(SaleOrderLine(3, 2.0, 50.0), SaleOrderLine(4, 1.0, 20.0)),
        state="draft",
        name="S00008",
        amount_total=120.0,
        company_id=2,
    )
    assert client.calls_to("sale.order", "read")[0] == {"ids": [8], "fields": ORDER_FIELDS}
    assert client.calls_to("sale.order.line", "read")[0] == {
        "ids": [11, 12],
        "fields": LINE_FIELDS,
    }


async def test_get_without_lines_or_company_skips_line_read(
    repo: OdooSaleOrderRepository, client: FakeOdooClient
) -> None:
    client.script("sale.order", "read", [order_row(order_line=[], company_id=False)])
    order = await repo.get(8)
    assert order is not None
    assert order.lines == ()
    assert order.company_id is None
    assert client.calls_to("sale.order.line", "read") == []


@pytest.mark.parametrize("result", [[], OdooNotFound("gone")])
async def test_get_returns_none_when_missing(
    repo: OdooSaleOrderRepository, client: FakeOdooClient, result: object
) -> None:
    client.script("sale.order", "read", result)
    assert await repo.get(8) is None


async def test_create_builds_order_lines_and_rereads(
    repo: OdooSaleOrderRepository, client: FakeOdooClient
) -> None:
    client.script("sale.order", "create", 8)
    script_get(client)
    created = await repo.create(
        SaleOrderData(
            customer_id=5,
            lines=(SaleOrderLine(3, 2.0, 50.0), SaleOrderLine(4, 1.0)),
            company_id=2,
        )
    )
    assert created.id == 8
    call = client.calls_to("sale.order", "create")[0]
    assert call["values"] == {
        "partner_id": 5,
        "company_id": 2,
        "order_line": [
            [0, 0, {"product_id": 3, "product_uom_qty": 2.0, "price_unit": 50.0}],
            [0, 0, {"product_id": 4, "product_uom_qty": 1.0}],
        ],
    }
    assert call["company_id"] == 2


async def test_create_without_company_omits_company(
    repo: OdooSaleOrderRepository, client: FakeOdooClient
) -> None:
    client.script("sale.order", "create", 8)
    script_get(client)
    await repo.create(SaleOrderData(customer_id=5, lines=(SaleOrderLine(3, 1.0),)))
    call = client.calls_to("sale.order", "create")[0]
    assert "company_id" not in call["values"]
    assert call["company_id"] is None


async def test_confirm_calls_action_confirm_then_rereads(
    repo: OdooSaleOrderRepository, client: FakeOdooClient
) -> None:
    client.script("sale.order", "action_confirm", True)
    script_get(client, "sale")
    confirmed = await repo.confirm(8)
    assert confirmed.state == "sale"
    assert client.calls_to("sale.order", "action_confirm") == [{"args": [[8]], "kwargs": None}]


async def test_confirm_missing_order_raises_not_found(
    repo: OdooSaleOrderRepository, client: FakeOdooClient
) -> None:
    client.script("sale.order", "action_confirm", OdooNotFound("gone"))
    with pytest.raises(OdooNotFound):
        await repo.confirm(8)


async def test_confirm_raises_not_found_when_reread_is_empty(
    repo: OdooSaleOrderRepository, client: FakeOdooClient
) -> None:
    client.script("sale.order", "action_confirm", True)
    client.script("sale.order", "read", [])
    with pytest.raises(OdooNotFound):
        await repo.confirm(8)
