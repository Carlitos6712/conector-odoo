"""``CustomerRepository`` adapter on ``res.partner``.

Country handling: the domain exposes an ISO ``country_code`` while Odoo stores a many2one to
``res.country``. Writes resolve the code with one ``search_read`` on ``res.country`` (``code`` is
the ISO alpha-2 code); reads resolve ids with one batched ``read`` of ``res.country``. Both
directions are cached in memory for the lifetime of the repository (countries are static data).

Search patterns: Odoo's ``ilike`` operator escapes ``\\``, ``%`` and ``_`` itself and wraps the
value in ``%...%`` (substring match), so the name filter passes the user value unchanged
(escaping it here would double-escape). ``=ilike`` is NOT escaped by Odoo: the value is handed
to SQL ``ILIKE`` as the full pattern, so ``%`` and ``_`` would act as wildcards. The email
filter therefore escapes them with ``escape_like`` and stays a case-insensitive exact match.
"""

from collections.abc import AsyncIterator
from typing import Any

from conector_odoo.application.pagination import DEFAULT_BATCH_SIZE
from conector_odoo.domain.entities import (
    Customer,
    CustomerData,
    CustomerFilter,
    CustomerQuery,
    CustomerUpdate,
)
from conector_odoo.domain.errors import OdooNotFound, OdooValidationError
from conector_odoo.infrastructure.odoo.client import OdooClient
from conector_odoo.infrastructure.odoo.mapping import many2one_id, read_back, text_or_none

MODEL = "res.partner"
FIELDS = [
    "name",
    "email",
    "phone",
    "street",
    "city",
    "zip",
    "country_id",
    "vat",
    "is_company",
    "active",
]
_PLAIN_FIELDS = ("name", "email", "phone", "street", "city", "zip", "vat", "is_company")


def escape_like(value: str) -> str:
    """Escape ``\\``, ``%`` and ``_`` so the value matches literally in a SQL ``ILIKE`` pattern."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class OdooCustomerRepository:
    def __init__(self, client: OdooClient, batch_size: int = DEFAULT_BATCH_SIZE) -> None:
        self._client = client
        self._batch_size = batch_size
        self._code_to_id: dict[str, int] = {}
        self._id_to_code: dict[int, str] = {}

    async def create(self, data: CustomerData) -> Customer:
        values = await self._to_values(
            {
                "name": data.name,
                "email": data.email,
                "phone": data.phone,
                "street": data.street,
                "city": data.city,
                "zip": data.zip,
                "country_code": data.country_code,
                "vat": data.vat,
                "is_company": data.is_company,
            }
        )
        customer_id = await self._client.create(MODEL, values)
        return await read_back(MODEL, customer_id, "customer", lambda: self.get(customer_id))

    async def update(self, customer_id: int, update: CustomerUpdate) -> Customer:
        values = await self._to_values(update.changes())
        if values:
            await self._client.write(MODEL, [customer_id], values)
        customer = await self.get(customer_id)
        if customer is None:
            raise OdooNotFound(f"customer {customer_id} not found")
        return customer

    async def get(self, customer_id: int) -> Customer | None:
        try:
            rows = await self._client.read(MODEL, [customer_id], FIELDS)
        except OdooNotFound:
            return None
        if not rows:
            return None
        return (await self._hydrate(rows))[0]

    async def search(self, query: CustomerQuery) -> list[Customer]:
        domain = self._domain(query.email, query.name)
        rows = await self._client.search_read(
            MODEL, domain, FIELDS, limit=query.limit, offset=query.offset, order="id asc"
        )
        return await self._hydrate(rows)

    async def iter_batches(
        self, filters: CustomerFilter, batch_size: int | None = None
    ) -> AsyncIterator[list[Customer]]:
        """Keyset-paginated export; country codes are resolved with one lookup per batch."""
        domain = self._domain(filters.email, filters.name)
        if filters.active is not None:
            domain.append(["active", "=", filters.active])  # explicit: includes archived
        async for rows in self._client.iter_search_read(
            MODEL, domain, FIELDS, batch_size=batch_size or self._batch_size
        ):
            yield await self._hydrate(rows)

    @staticmethod
    def _domain(email: str | None, name: str | None) -> list[Any]:
        domain: list[Any] = []
        if email:
            domain.append(["email", "=ilike", escape_like(email)])
        if name:
            domain.append(["name", "ilike", name])
        return domain

    async def archive(self, customer_id: int) -> None:
        await self._client.write(MODEL, [customer_id], {"active": False})

    async def _to_values(self, changes: dict[str, Any]) -> dict[str, Any]:
        values = {
            key: changes[key]
            for key in _PLAIN_FIELDS
            if key in changes and changes[key] is not None
        }
        code = changes.get("country_code")
        if code:
            values["country_id"] = await self._country_id(str(code))
        return values

    async def _country_id(self, code: str) -> int:
        code = code.upper()
        if code not in self._code_to_id:
            rows = await self._client.search_read(
                "res.country", [["code", "=", code]], ["code"], limit=1
            )
            if not rows:
                raise OdooValidationError(f"unknown country code {code!r}")
            country_id = int(rows[0]["id"])
            self._code_to_id[code] = country_id
            self._id_to_code[country_id] = code
        return self._code_to_id[code]

    async def _hydrate(self, rows: list[dict[str, Any]]) -> list[Customer]:
        missing = {
            cid
            for row in rows
            if (cid := many2one_id(row.get("country_id"))) is not None
            and cid not in self._id_to_code
        }
        if missing:
            for country in await self._client.read("res.country", sorted(missing), ["code"]):
                code = text_or_none(country.get("code"))
                if code:
                    self._id_to_code[int(country["id"])] = code
                    self._code_to_id[code] = int(country["id"])
        return [self._to_customer(row) for row in rows]

    def _to_customer(self, row: dict[str, Any]) -> Customer:
        country_id = many2one_id(row.get("country_id"))
        return Customer(
            id=int(row["id"]),
            name=str(row.get("name") or ""),
            email=text_or_none(row.get("email")),
            phone=text_or_none(row.get("phone")),
            street=text_or_none(row.get("street")),
            city=text_or_none(row.get("city")),
            zip=text_or_none(row.get("zip")),
            country_code=self._id_to_code.get(country_id) if country_id is not None else None,
            vat=text_or_none(row.get("vat")),
            is_company=bool(row.get("is_company", False)),
            active=bool(row.get("active", True)),
        )
