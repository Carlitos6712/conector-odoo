import pytest

from conector_odoo.application.customers import (
    CreateCustomer,
    GetCustomer,
    SearchCustomers,
    UpdateCustomer,
)
from conector_odoo.domain.entities import CustomerData, CustomerQuery, CustomerUpdate
from conector_odoo.domain.errors import ConnectorError, OdooNotFound, OdooValidationError
from tests.unit.fakes import FakeCustomerRepository


async def test_create_customer_returns_customer_with_id() -> None:
    repo = FakeCustomerRepository()
    customer = await CreateCustomer(repo).execute(CustomerData(name="Acme", email="a@acme.io"))
    assert customer.id == 1
    assert customer.name == "Acme"
    assert customer.active is True


async def test_create_customer_rejects_blank_name() -> None:
    repo = FakeCustomerRepository()
    with pytest.raises(OdooValidationError):
        await CreateCustomer(repo).execute(CustomerData(name="   "))
    assert repo.calls == []


async def test_update_customer_applies_partial_changes() -> None:
    repo = FakeCustomerRepository()
    created = await CreateCustomer(repo).execute(CustomerData(name="Acme", city="Paris"))
    assert created.id is not None
    updated = await UpdateCustomer(repo).execute(created.id, CustomerUpdate(phone="123"))
    assert updated.phone == "123"
    assert updated.city == "Paris"


async def test_update_customer_with_empty_update_is_rejected() -> None:
    repo = FakeCustomerRepository()
    with pytest.raises(OdooValidationError):
        await UpdateCustomer(repo).execute(1, CustomerUpdate())
    assert repo.calls == []


async def test_get_customer_raises_not_found() -> None:
    with pytest.raises(OdooNotFound):
        await GetCustomer(FakeCustomerRepository()).execute(99)


async def test_get_customer_returns_existing() -> None:
    repo = FakeCustomerRepository()
    created = await CreateCustomer(repo).execute(CustomerData(name="Acme"))
    assert created.id is not None
    assert await GetCustomer(repo).execute(created.id) == created


async def test_search_customers_filters_and_paginates() -> None:
    repo = FakeCustomerRepository()
    create = CreateCustomer(repo)
    for name in ("Acme One", "Acme Two", "Other"):
        await create.execute(CustomerData(name=name))
    found = await SearchCustomers(repo).execute(CustomerQuery(name="acme", limit=1, offset=1))
    assert [c.name for c in found] == ["Acme Two"]


@pytest.mark.parametrize("limit,offset", [(0, 0), (-1, 0), (10, -1), (1001, 0)])
async def test_search_customers_validates_pagination(limit: int, offset: int) -> None:
    with pytest.raises(OdooValidationError):
        await SearchCustomers(FakeCustomerRepository()).execute(
            CustomerQuery(limit=limit, offset=offset)
        )


def test_domain_errors_share_a_base() -> None:
    assert issubclass(OdooValidationError, ConnectorError)
    assert issubclass(OdooNotFound, ConnectorError)


def test_customer_update_changes_only_includes_set_fields() -> None:
    update = CustomerUpdate(name="X", vat=None, email="e@x.io")
    assert update.changes() == {"name": "X", "email": "e@x.io"}
    assert not update.is_empty()
    assert CustomerUpdate().is_empty()
