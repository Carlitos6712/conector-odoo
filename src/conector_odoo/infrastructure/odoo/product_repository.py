"""``ProductRepository`` adapter on ``product.product``.

``list_price`` is read from ``lst_price`` (the variant price, i.e. template price plus extras),
which is what a sale order line uses by default. ``uom_name`` is the display name of ``uom_id``.
"""

from typing import Any

from conector_odoo.domain.entities import Product
from conector_odoo.domain.errors import OdooNotFound
from conector_odoo.infrastructure.odoo.client import OdooClient
from conector_odoo.infrastructure.odoo.mapping import many2one_name, text_or_none

MODEL = "product.product"
FIELDS = ["name", "default_code", "lst_price", "uom_id", "active"]


class OdooProductRepository:
    def __init__(self, client: OdooClient) -> None:
        self._client = client

    async def get(self, product_id: int) -> Product | None:
        try:
            rows = await self._client.read(MODEL, [product_id], FIELDS)
        except OdooNotFound:
            return None
        return self._to_product(rows[0]) if rows else None

    async def list(self, limit: int, offset: int) -> list[Product]:
        rows = await self._client.search_read(
            MODEL, [["sale_ok", "=", True]], FIELDS, limit=limit, offset=offset, order="id asc"
        )
        return [self._to_product(row) for row in rows]

    @staticmethod
    def _to_product(row: dict[str, Any]) -> Product:
        return Product(
            id=int(row["id"]),
            name=str(row.get("name") or ""),
            default_code=text_or_none(row.get("default_code")),
            list_price=float(row.get("lst_price") or 0.0),
            uom_name=many2one_name(row.get("uom_id")),
            active=bool(row.get("active", True)),
        )
