"""Domain entities and input DTOs. Pure Python: no framework imports."""

from dataclasses import dataclass, fields
from typing import Any


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
