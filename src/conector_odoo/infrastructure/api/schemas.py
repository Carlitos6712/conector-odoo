"""Pydantic v2 request/response models and their mapping to and from domain entities.

Pydantic lives only in this layer; the domain keeps plain dataclasses.
"""

import re
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from conector_odoo.domain.entities import (
    Customer,
    CustomerData,
    CustomerUpdate,
    Product,
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
