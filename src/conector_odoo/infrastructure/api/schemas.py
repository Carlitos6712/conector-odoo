"""Pydantic v2 request/response models and their mapping to and from domain entities.

Pydantic lives only in this layer; the domain keeps plain dataclasses.
"""

import re
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

from conector_odoo.domain.entities import (
    BulkStatus,
    Customer,
    CustomerData,
    CustomerUpdate,
    CustomerUpsert,
    Product,
    RejectedItem,
    SaleOrder,
    SaleOrderData,
    SaleOrderLine,
)

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_COUNTRY = r"^[A-Za-z]{2}$"


def _validate_email(value: str) -> str:
    if len(value) > 254 or not _EMAIL.match(value):
        raise ValueError("not a valid email address")
    return value


Email = Annotated[str, AfterValidator(_validate_email)]
CountryCode = Annotated[str, Field(pattern=_COUNTRY)]
PositiveId = Annotated[int, Field(gt=0)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CustomerCreate(_Strict):
    name: str = Field(min_length=1, max_length=255)
    email: Email | None = None
    phone: str | None = Field(default=None, max_length=64)
    street: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=128)
    zip: str | None = Field(default=None, max_length=32)
    country_code: CountryCode | None = None
    vat: str | None = Field(default=None, max_length=64)
    is_company: bool = False

    def to_domain(self) -> CustomerData:
        return CustomerData(**self.model_dump())


class CustomerPatch(_Strict):
    """Partial update. ``null`` means "leave unchanged"; a body without values is rejected."""

    name: str | None = Field(default=None, max_length=255)
    email: Email | None = None
    phone: str | None = Field(default=None, max_length=64)
    street: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=128)
    zip: str | None = Field(default=None, max_length=32)
    country_code: CountryCode | None = None
    vat: str | None = Field(default=None, max_length=64)
    is_company: bool | None = None

    @model_validator(mode="after")
    def _at_least_one_value(self) -> Self:
        if all(value is None for value in self.model_dump().values()):
            raise ValueError("at least one field must be provided")
        return self

    def to_domain(self) -> CustomerUpdate:
        return CustomerUpdate(**self.model_dump())


class CustomerOut(BaseModel):
    id: int | None
    name: str
    email: str | None
    phone: str | None
    street: str | None
    city: str | None
    zip: str | None
    country_code: str | None
    vat: str | None
    is_company: bool
    active: bool

    @classmethod
    def from_domain(cls, customer: Customer) -> Self:
        return cls(
            id=customer.id,
            name=customer.name,
            email=customer.email,
            phone=customer.phone,
            street=customer.street,
            city=customer.city,
            zip=customer.zip,
            country_code=customer.country_code,
            vat=customer.vat,
            is_company=customer.is_company,
            active=customer.active,
        )


class BulkCustomerItem(_Strict):
    """One item of ``POST /customers/bulk``.

    Structure is validated here (types, lengths, required name); semantic problems that only
    affect one item (bad email) become ``RejectedItem`` results instead of rejecting the whole
    payload, so one bad row never fails a large import.
    """

    name: str = Field(min_length=1, max_length=255)
    # Not the ``Email`` type on purpose: format is checked per item in ``to_domain``.
    email: str | None = None
    phone: str | None = Field(default=None, max_length=64)
    street: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=128)
    zip: str | None = Field(default=None, max_length=32)
    country_code: CountryCode | None = None
    vat: str | None = Field(default=None, max_length=64)
    is_company: bool | None = None

    def to_domain(self) -> CustomerUpsert | RejectedItem:
        email = (self.email or "").strip() or None
        if email is not None:
            try:
                _validate_email(email)
            except ValueError:
                # The input value is never echoed back (it may hold personal data).
                return RejectedItem("email: not a valid email address")
        return CustomerUpsert(
            name=self.name,
            email=email,
            phone=self.phone,
            street=self.street,
            city=self.city,
            zip=self.zip,
            country_code=self.country_code,
            vat=self.vat,
            is_company=self.is_company,
        )


class BulkCustomersIn(_Strict):
    """Envelope of ``POST /customers/bulk``: create-or-update by email in one request."""

    items: list[BulkCustomerItem] = Field(min_length=1)
    match_by: Literal["email"] = "email"

    def to_domain(self) -> list[CustomerUpsert | RejectedItem]:
        return [item.to_domain() for item in self.items]


class BulkItemResultOut(BaseModel):
    index: int
    status: BulkStatus
    id: int | None
    error: str | None


class BulkCustomersOut(BaseModel):
    created: int
    updated: int
    failed: int
    results: list[BulkItemResultOut]


class ProductOut(BaseModel):
    id: int
    name: str
    default_code: str | None
    list_price: float
    uom_name: str | None
    active: bool

    @classmethod
    def from_domain(cls, product: Product) -> Self:
        return cls(
            id=product.id,
            name=product.name,
            default_code=product.default_code,
            list_price=product.list_price,
            uom_name=product.uom_name,
            active=product.active,
        )


class SaleOrderLineIn(_Strict):
    product_id: PositiveId
    quantity: float = Field(gt=0)
    price_unit: float | None = Field(default=None, ge=0)

    def to_domain(self) -> SaleOrderLine:
        return SaleOrderLine(self.product_id, self.quantity, self.price_unit)


class SaleOrderLineOut(BaseModel):
    product_id: int
    quantity: float
    price_unit: float | None


class SaleOrderCreate(_Strict):
    customer_id: PositiveId
    lines: list[SaleOrderLineIn] = Field(min_length=1)
    company_id: PositiveId | None = None

    def to_domain(self) -> SaleOrderData:
        return SaleOrderData(
            customer_id=self.customer_id,
            lines=tuple(line.to_domain() for line in self.lines),
            company_id=self.company_id,
        )


class SaleOrderOut(BaseModel):
    id: int
    customer_id: int
    lines: list[SaleOrderLineOut]
    state: str
    name: str
    amount_total: float
    company_id: int | None

    @classmethod
    def from_domain(cls, order: SaleOrder) -> Self:
        return cls(
            id=order.id,
            customer_id=order.customer_id,
            lines=[
                SaleOrderLineOut(
                    product_id=line.product_id,
                    quantity=line.quantity,
                    price_unit=line.price_unit,
                )
                for line in order.lines
            ],
            state=order.state,
            name=order.name,
            amount_total=order.amount_total,
            company_id=order.company_id,
        )


class HealthOut(BaseModel):
    status: Literal["ok"]
    odoo: Literal["reachable"]
    uid: int | None
    protocol: str


class DegradedHealthOut(BaseModel):
    status: Literal["degraded"]
    detail: str


class ErrorOut(BaseModel):
    error: str
    detail: str


class WebhookEventIn(BaseModel):
    """Event pushed by the Odoo addon. Unknown extra fields are ignored (forward compatible).

    ``event_type`` is a free string on purpose: an unknown type is acknowledged and ignored (so a
    newer addon never gets retries from an older connector) rather than rejected with 422.
    ``occurred_at`` without a timezone is interpreted as UTC.
    """

    event_id: UUID
    event_type: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=100)
    record_id: PositiveId
    occurred_at: datetime
    payload: dict[str, Any]

    @field_validator("occurred_at")
    @classmethod
    def _assume_utc(cls, value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class WebhookAck(BaseModel):
    status: Literal["accepted", "duplicate", "ignored"]
    event_id: str
