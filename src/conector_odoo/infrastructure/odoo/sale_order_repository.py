"""``SaleOrderRepository`` adapter on ``sale.order`` / ``sale.order.line``.

Lines are created through the ``order_line`` one2many command ``[0, 0, values]`` (JSON friendly
lists, not tuples). ``price_unit`` is omitted when ``None`` so Odoo applies the pricelist.
``company_id`` is set on the order and also passed as the call company so the context matches;
the read-back after ``create`` uses the same company so it sees the record that was just created.
If that read-back fails the order already exists in Odoo, so the error says so (with the id)
instead of surfacing as a plain failure that would invite a duplicate create.
"""

from typing import Any

from conector_odoo.domain.entities import SaleOrder, SaleOrderData, SaleOrderLine
from conector_odoo.domain.errors import ConnectorError, OdooNotFound, OdooUnavailable
from conector_odoo.infrastructure.odoo.client import OdooClient
from conector_odoo.infrastructure.odoo.mapping import many2one_id

ORDER_MODEL = "sale.order"
LINE_MODEL = "sale.order.line"
ORDER_FIELDS = ["partner_id", "order_line", "state", "name", "amount_total", "company_id"]
LINE_FIELDS = ["product_id", "product_uom_qty", "price_unit"]


class OdooSaleOrderRepository:
    def __init__(self, client: OdooClient) -> None:
        self._client = client

    async def create(self, data: SaleOrderData) -> SaleOrder:
        values: dict[str, Any] = {
            "partner_id": data.customer_id,
            "order_line": [[0, 0, self._line_values(line)] for line in data.lines],
        }
        if data.company_id is not None:
            values["company_id"] = data.company_id
        order_id = await self._client.create(ORDER_MODEL, values, company_id=data.company_id)
        try:
            order = await self._read(order_id, data.company_id)
        except ConnectorError as exc:
            raise OdooUnavailable(
                f"sale order {order_id} was created but could not be read back"
            ) from exc
        if order is None:
            raise OdooUnavailable(f"sale order {order_id} was created but could not be read back")
        return order

    async def confirm(self, order_id: int) -> SaleOrder:
        await self._client.execute_kw(ORDER_MODEL, "action_confirm", [[order_id]])
        order = await self.get(order_id)
        if order is None:
            raise OdooNotFound(f"sale order {order_id} not found")
        return order

    async def get(self, order_id: int) -> SaleOrder | None:
        return await self._read(order_id, None)

    async def _read(self, order_id: int, company_id: int | None) -> SaleOrder | None:
        try:
            rows = await self._client.read(
                ORDER_MODEL, [order_id], ORDER_FIELDS, company_id=company_id
            )
        except OdooNotFound:
            return None
        if not rows:
            return None
        row = rows[0]
        line_ids = [int(i) for i in row.get("order_line") or []]
        line_rows = (
            await self._client.read(LINE_MODEL, line_ids, LINE_FIELDS, company_id=company_id)
            if line_ids
            else []
        )
        return SaleOrder(
            id=int(row["id"]),
            customer_id=many2one_id(row.get("partner_id")) or 0,
            lines=tuple(self._to_line(line) for line in line_rows),
            state=str(row.get("state") or ""),
            name=str(row.get("name") or ""),
            amount_total=float(row.get("amount_total") or 0.0),
            company_id=many2one_id(row.get("company_id")),
        )

    @staticmethod
    def _line_values(line: SaleOrderLine) -> dict[str, Any]:
        values: dict[str, Any] = {"product_id": line.product_id, "product_uom_qty": line.quantity}
        if line.price_unit is not None:
            values["price_unit"] = line.price_unit
        return values

    @staticmethod
    def _to_line(row: dict[str, Any]) -> SaleOrderLine:
        return SaleOrderLine(
            product_id=many2one_id(row.get("product_id")) or 0,
            quantity=float(row.get("product_uom_qty") or 0.0),
            price_unit=float(row["price_unit"]) if row.get("price_unit") is not None else None,
        )
