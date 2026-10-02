from typing import Annotated

from fastapi import APIRouter, Depends, Path

from conector_odoo.application.sale_orders import ConfirmSaleOrder, CreateSaleOrder
from conector_odoo.domain.errors import OdooNotFound
from conector_odoo.infrastructure.api.dependencies import (
    SaleOrderRepo,
    get_confirm_sale_order,
    get_create_sale_order,
)
from conector_odoo.infrastructure.api.schemas import ErrorOut, SaleOrderCreate, SaleOrderOut
from conector_odoo.infrastructure.api.security import require_api_key

router = APIRouter(
    prefix="/sale-orders",
    tags=["sale-orders"],
    dependencies=[Depends(require_api_key)],
    responses={401: {"model": ErrorOut}},
)

OrderId = Annotated[int, Path(gt=0)]


@router.post("", status_code=201, response_model=SaleOrderOut)
async def create_sale_order(
    body: SaleOrderCreate,
    use_case: Annotated[CreateSaleOrder, Depends(get_create_sale_order)],
) -> SaleOrderOut:
    return SaleOrderOut.from_domain(await use_case.execute(body.to_domain()))


@router.post(
    "/{order_id}/confirm", response_model=SaleOrderOut, responses={404: {"model": ErrorOut}}
)
async def confirm_sale_order(
    order_id: OrderId, use_case: Annotated[ConfirmSaleOrder, Depends(get_confirm_sale_order)]
) -> SaleOrderOut:
    return SaleOrderOut.from_domain(await use_case.execute(order_id))


@router.get("/{order_id}", response_model=SaleOrderOut, responses={404: {"model": ErrorOut}})
async def get_sale_order(order_id: OrderId, orders: SaleOrderRepo) -> SaleOrderOut:
    order = await orders.get(order_id)
    if order is None:
        raise OdooNotFound(f"sale order {order_id} not found")
    return SaleOrderOut.from_domain(order)
