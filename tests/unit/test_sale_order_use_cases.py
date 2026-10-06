from dataclasses import replace

import pytest

from conector_odoo.application.sale_orders import ConfirmSaleOrder, CreateSaleOrder, GetSaleOrder
from conector_odoo.domain.entities import SaleOrderData, SaleOrderLine
from conector_odoo.domain.errors import OdooNotFound, OdooValidationError
from tests.unit.fakes import FakeSaleOrderRepository


def _data(*lines: SaleOrderLine) -> SaleOrderData:
    return SaleOrderData(customer_id=5, lines=tuple(lines))


async def test_create_sale_order_persists_lines() -> None:
    repo = FakeSaleOrderRepository()
    order = await CreateSaleOrder(repo).execute(
        _data(SaleOrderLine(product_id=1, quantity=2, price_unit=9.5))
    )
    assert order.id == 1
    assert order.state == "draft"
    assert order.lines[0].quantity == 2


async def test_create_sale_order_rejects_empty_lines() -> None:
    repo = FakeSaleOrderRepository()
    with pytest.raises(OdooValidationError):
        await CreateSaleOrder(repo).execute(_data())
    assert repo.items == {}


@pytest.mark.parametrize("quantity", [0, -1, -0.5])
async def test_create_sale_order_rejects_non_positive_quantity(quantity: float) -> None:
    repo = FakeSaleOrderRepository()
    with pytest.raises(OdooValidationError):
        await CreateSaleOrder(repo).execute(_data(SaleOrderLine(product_id=1, quantity=quantity)))
    assert repo.items == {}


async def test_create_sale_order_rejects_negative_price() -> None:
    with pytest.raises(OdooValidationError):
        await CreateSaleOrder(FakeSaleOrderRepository()).execute(
            _data(SaleOrderLine(product_id=1, quantity=1, price_unit=-1))
        )


async def test_confirm_moves_draft_to_sale() -> None:
    repo = FakeSaleOrderRepository()
    created = await CreateSaleOrder(repo).execute(_data(SaleOrderLine(product_id=1, quantity=1)))
    confirmed = await ConfirmSaleOrder(repo).execute(created.id)
    assert confirmed.state == "sale"


async def test_confirm_is_noop_when_already_confirmed() -> None:
    repo = FakeSaleOrderRepository()
    created = await CreateSaleOrder(repo).execute(_data(SaleOrderLine(product_id=1, quantity=1)))
    use_case = ConfirmSaleOrder(repo)
    await use_case.execute(created.id)
    again = await use_case.execute(created.id)
    assert again.state == "sale"
    assert repo.confirm_calls == 1


async def test_confirm_missing_order_raises_not_found() -> None:
    with pytest.raises(OdooNotFound):
        await ConfirmSaleOrder(FakeSaleOrderRepository()).execute(404)


async def test_confirm_cancelled_order_is_rejected() -> None:
    repo = FakeSaleOrderRepository()
    created = await CreateSaleOrder(repo).execute(_data(SaleOrderLine(product_id=1, quantity=1)))
    repo.items[created.id] = replace(created, state="cancel")
    with pytest.raises(OdooValidationError):
        await ConfirmSaleOrder(repo).execute(created.id)


async def test_get_sale_order_returns_the_order_and_forwards_the_company() -> None:
    repo = FakeSaleOrderRepository()
    created = await CreateSaleOrder(repo).execute(_data(SaleOrderLine(product_id=1, quantity=1)))
    assert await GetSaleOrder(repo).execute(created.id, company_id=3) == created
    assert repo.get_companies == [3]


async def test_get_sale_order_raises_not_found_when_missing() -> None:
    with pytest.raises(OdooNotFound):
        await GetSaleOrder(FakeSaleOrderRepository()).execute(99)


async def test_confirm_sale_order_forwards_the_company() -> None:
    repo = FakeSaleOrderRepository()
    created = await CreateSaleOrder(repo).execute(_data(SaleOrderLine(product_id=1, quantity=1)))
    await ConfirmSaleOrder(repo).execute(created.id, company_id=3)
    assert repo.get_companies == [3]
    assert repo.confirm_companies == [3]
