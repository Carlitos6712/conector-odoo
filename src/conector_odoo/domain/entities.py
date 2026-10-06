"""Domain entities and input DTOs. Pure Python: no framework imports."""

from dataclasses import dataclass, fields
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class Customer:
    id: int | None
    name: str
    email: str | None = None
    phone: str | None = None
    street: str | None = None
    city: str | None = None
    zip: str | None = None
    country_code: str | None = None
    vat: str | None = None
    is_company: bool = False
    active: bool = True


@dataclass(frozen=True, slots=True)
class CustomerData:
    """Input for creating a customer."""

    name: str
    email: str | None = None
    phone: str | None = None
    street: str | None = None
    city: str | None = None
    zip: str | None = None
    country_code: str | None = None
    vat: str | None = None
    is_company: bool = False


@dataclass(frozen=True, slots=True)
class CustomerUpdate:
    """Partial update: ``None`` means "leave unchanged"."""

    name: str | None = None
    email: str | None = None
    phone: str | None = None
    street: str | None = None
    city: str | None = None
    zip: str | None = None
    country_code: str | None = None
    vat: str | None = None
    is_company: bool | None = None

    def changes(self) -> dict[str, Any]:
        """Return only the fields that were provided."""
        values = {f.name: getattr(self, f.name) for f in fields(self)}
        return {key: value for key, value in values.items() if value is not None}

    def is_empty(self) -> bool:
        return not self.changes()


@dataclass(frozen=True, slots=True)
class CustomerQuery:
    email: str | None = None
    name: str | None = None
    limit: int = 50
    offset: int = 0


@dataclass(frozen=True, slots=True)
class CustomerUpsert:
    """One item of a bulk upsert. ``is_company=None`` means "not provided" (left unchanged on an
    update, ``False`` on a create)."""

    name: str
    email: str | None = None
    phone: str | None = None
    street: str | None = None
    city: str | None = None
    zip: str | None = None
    country_code: str | None = None
    vat: str | None = None
    is_company: bool | None = None

    def to_data(self) -> CustomerData:
        values = {f.name: getattr(self, f.name) for f in fields(self)}
        values["is_company"] = bool(self.is_company)
        return CustomerData(**values)

    def to_update(self) -> CustomerUpdate:
        """Fields to write on an existing record; the email is the match key, never rewritten."""
        values = {f.name: getattr(self, f.name) for f in fields(self)}
        values["email"] = None
        return CustomerUpdate(**values)


@dataclass(frozen=True, slots=True)
class RejectedItem:
    """A bulk item that failed validation before reaching the use case."""

    reason: str


BulkStatus = Literal["created", "updated", "failed"]


@dataclass(frozen=True, slots=True)
class BulkItemResult:
    index: int
    status: BulkStatus
    id: int | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class BulkUpsertResult:
    results: list[BulkItemResult]

    @property
    def created(self) -> int:
        return sum(r.status == "created" for r in self.results)

    @property
    def updated(self) -> int:
        return sum(r.status == "updated" for r in self.results)

    @property
    def failed(self) -> int:
        return sum(r.status == "failed" for r in self.results)


@dataclass(frozen=True, slots=True)
class CustomerFilter:
    """Filters for exporting customers. ``active=None`` keeps the Odoo default (active only)."""

    email: str | None = None
    name: str | None = None
    active: bool | None = None


@dataclass(frozen=True, slots=True)
class Product:
    id: int
    name: str
    default_code: str | None = None
    list_price: float = 0.0
    uom_name: str | None = None
    active: bool = True


@dataclass(frozen=True, slots=True)
class SaleOrderLine:
    product_id: int
    quantity: float
    price_unit: float | None = None


@dataclass(frozen=True, slots=True)
class SaleOrderData:
    """Input for creating a sale order."""

    customer_id: int
    lines: tuple[SaleOrderLine, ...]
    company_id: int | None = None


@dataclass(frozen=True, slots=True)
class SaleOrder:
    id: int
    customer_id: int
    lines: tuple[SaleOrderLine, ...]
    state: str
    name: str
    amount_total: float
    company_id: int | None = None
