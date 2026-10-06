import pytest

from conector_odoo.application.customers import ExportCustomers
from conector_odoo.application.products import ExportProducts
from conector_odoo.domain.entities import Customer, CustomerData, CustomerFilter, Product
from conector_odoo.domain.errors import OdooUnavailable, OdooValidationError
from tests.unit.fakes import FakeCustomerRepository, FakeProductRepository


async def seeded_customers(count: int) -> FakeCustomerRepository:
    repo = FakeCustomerRepository()
    for i in range(count):
        await repo.create(CustomerData(name=f"C{i}", email=f"c{i}@x.io"))
    return repo


async def test_export_customers_yields_every_batch_in_order() -> None:
    repo = await seeded_customers(5)
    batches = [b async for b in ExportCustomers(repo).execute(CustomerFilter(), 2)]
    assert [[c.id for c in b] for b in batches] == [[1, 2], [3, 4], [5]]
    assert all(isinstance(c, Customer) for b in batches for c in b)


async def test_export_customers_passes_filters_and_batch_size_down() -> None:
    repo = await seeded_customers(3)
    filters = CustomerFilter(email="c1@x.io", name="C", active=True)
    rows: list[Customer] = []
    async for batch in ExportCustomers(repo).execute(filters, 7):
        rows.extend(batch)
    assert [c.id for c in rows] == [2]
    assert repo.export_calls == [(filters, 7)]


async def test_export_customers_without_batch_size_leaves_the_default_to_the_adapter() -> None:
    repo = await seeded_customers(1)
    async for _ in ExportCustomers(repo).execute(CustomerFilter(), None):
        pass
    assert repo.export_calls[0][1] is None


@pytest.mark.parametrize("size", [0, -1, 5001])
def test_export_customers_rejects_bad_batch_size_eagerly(size: int) -> None:
    repo = FakeCustomerRepository()
    with pytest.raises(OdooValidationError):
        ExportCustomers(repo).execute(CustomerFilter(), size)
    assert repo.export_calls == []


async def test_export_customers_propagates_repository_errors() -> None:
    repo = await seeded_customers(4)
    repo.export_error = OdooUnavailable("down")
    seen: list[int] = []
    with pytest.raises(OdooUnavailable):
        async for batch in ExportCustomers(repo).execute(CustomerFilter(), 2):
            seen.extend(c.id or 0 for c in batch)
    assert seen == [1, 2]


async def test_export_products_yields_batches() -> None:
    repo = FakeProductRepository([Product(id=i, name=f"P{i}") for i in range(1, 6)])
    batches = [b async for b in ExportProducts(repo).execute(2)]
    assert [[p.id for p in b] for b in batches] == [[1, 2], [3, 4], [5]]
    assert repo.export_calls == [2]


@pytest.mark.parametrize("size", [0, 5001])
def test_export_products_rejects_bad_batch_size(size: int) -> None:
    with pytest.raises(OdooValidationError):
        ExportProducts(FakeProductRepository()).execute(size)
