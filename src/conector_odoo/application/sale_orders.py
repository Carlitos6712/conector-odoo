"""Sale order use cases."""

from conector_odoo.domain.entities import SaleOrder, SaleOrderData
from conector_odoo.domain.errors import OdooNotFound, OdooValidationError
from conector_odoo.domain.ports import SaleOrderRepository

_CONFIRMED_STATES = frozenset({"sale", "done"})


class CreateSaleOrder:
    def __init__(self, orders: SaleOrderRepository) -> None:
        self._orders = orders

    async def execute(self, data: SaleOrderData) -> SaleOrder:
        if not data.lines:
            raise OdooValidationError("a sale order needs at least one line")
        for line in data.lines:
            if line.quantity <= 0:
                raise OdooValidationError("line quantity must be greater than zero")
            if line.price_unit is not None and line.price_unit < 0:
                raise OdooValidationError("line price_unit must not be negative")
        return await self._orders.create(data)


class ConfirmSaleOrder:
    def __init__(self, orders: SaleOrderRepository) -> None:
        self._orders = orders

    async def execute(self, order_id: int) -> SaleOrder:
        order = await self._orders.get(order_id)
        if order is None:
            raise OdooNotFound(f"sale order {order_id} not found")
        if order.state in _CONFIRMED_STATES:
            return order
        if order.state == "cancel":
            raise OdooValidationError("a cancelled sale order cannot be confirmed")
        return await self._orders.confirm(order_id)
