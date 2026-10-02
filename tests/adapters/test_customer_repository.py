import pytest

from conector_odoo.domain.entities import Customer, CustomerData, CustomerQuery, CustomerUpdate
from conector_odoo.domain.errors import OdooNotFound, OdooValidationError
from conector_odoo.infrastructure.odoo.customer_repository import OdooCustomerRepository
from tests.adapters.fake_odoo_client import FakeOdooClient

PARTNER_FIELDS = [
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


def partner(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": 5,
        "name": "Ada",
        "email": "ada@x.io",
        "phone": False,
        "street": False,
        "city": "Madrid",
        "zip": False,
        "country_id": [68, "Spain"],
        "vat": False,
        "is_company": False,
        "active": True,
    }
    row.update(overrides)
    return row


@pytest.fixture
def client() -> FakeOdooClient:
    return FakeOdooClient()


@pytest.fixture
def repo(client: FakeOdooClient) -> OdooCustomerRepository:
    return OdooCustomerRepository(client)  # type: ignore[arg-type]


async def test_get_maps_false_to_none_and_resolves_country_code(
    repo: OdooCustomerRepository, client: FakeOdooClient
) -> None:
    client.script("res.partner", "read", [partner()])
    client.script("res.country", "read", [{"id": 68, "code": "ES"}])
    customer = await repo.get(5)
    assert customer == Customer(
        id=5, name="Ada", email="ada@x.io", city="Madrid", country_code="ES"
    )
    assert client.calls_to("res.partner", "read")[0] == {"ids": [5], "fields": PARTNER_FIELDS}


async def test_get_returns_none_for_empty_read(
    repo: OdooCustomerRepository, client: FakeOdooClient
) -> None:
    client.script("res.partner", "read", [])
    assert await repo.get(99) is None


async def test_get_returns_none_when_odoo_reports_missing(
    repo: OdooCustomerRepository, client: FakeOdooClient
) -> None:
    client.script("res.partner", "read", OdooNotFound("gone"))
    assert await repo.get(99) is None


async def test_country_without_value_needs_no_lookup(
    repo: OdooCustomerRepository, client: FakeOdooClient
) -> None:
    client.script("res.partner", "read", [partner(country_id=False)])
    customer = await repo.get(5)
    assert customer is not None
    assert customer.country_code is None
    assert client.calls_to("res.country", "read") == []


async def test_country_codes_are_cached(
    repo: OdooCustomerRepository, client: FakeOdooClient
) -> None:
    client.script("res.partner", "read", [partner()], [partner(id=6)])
    client.script("res.country", "read", [{"id": 68, "code": "ES"}])
    await repo.get(5)
    second = await repo.get(6)
    assert second is not None
    assert second.country_code == "ES"
    assert len(client.calls_to("res.country", "read")) == 1


async def test_create_resolves_country_id_creates_and_rereads(
    repo: OdooCustomerRepository, client: FakeOdooClient
) -> None:
    client.script("res.country", "search_read", [{"id": 68, "code": "ES"}])
    client.script("res.partner", "create", 5)
    client.script("res.partner", "read", [partner()])
    created = await repo.create(
        CustomerData(name="Ada", email="ada@x.io", city="Madrid", country_code="es")
    )
    assert created.id == 5
    assert created.country_code == "ES"
    assert client.calls_to("res.country", "search_read")[0]["domain"] == [["code", "=", "ES"]]
    assert client.calls_to("res.partner", "create")[0]["values"] == {
        "name": "Ada",
        "email": "ada@x.io",
        "city": "Madrid",
        "country_id": 68,
        "is_company": False,
    }


async def test_create_with_unknown_country_is_validation_error(
    repo: OdooCustomerRepository, client: FakeOdooClient
) -> None:
    client.script("res.country", "search_read", [])
    with pytest.raises(OdooValidationError):
        await repo.create(CustomerData(name="Ada", country_code="ZZ"))
    assert client.calls_to("res.partner", "create") == []


async def test_update_writes_only_changes_then_rereads(
    repo: OdooCustomerRepository, client: FakeOdooClient
) -> None:
    client.script("res.partner", "write", True)
    client.script("res.partner", "read", [partner(name="Ada L.")])
    client.script("res.country", "read", [{"id": 68, "code": "ES"}])
    updated = await repo.update(5, CustomerUpdate(name="Ada L."))
    assert updated.name == "Ada L."
    assert client.calls_to("res.partner", "write") == [{"ids": [5], "values": {"name": "Ada L."}}]


async def test_update_missing_customer_raises_not_found(
    repo: OdooCustomerRepository, client: FakeOdooClient
) -> None:
    client.script("res.partner", "write", OdooNotFound("gone"))
    with pytest.raises(OdooNotFound):
        await repo.update(5, CustomerUpdate(name="x"))


async def test_update_raises_not_found_when_reread_is_empty(
    repo: OdooCustomerRepository, client: FakeOdooClient
) -> None:
    client.script("res.partner", "write", True)
    client.script("res.partner", "read", [])
    with pytest.raises(OdooNotFound):
        await repo.update(5, CustomerUpdate(name="x"))


async def test_search_builds_domain_and_paging(
    repo: OdooCustomerRepository, client: FakeOdooClient
) -> None:
    client.script("res.partner", "search_read", [partner(), partner(id=6, country_id=False)])
    client.script("res.country", "read", [{"id": 68, "code": "ES"}])
    result = await repo.search(CustomerQuery(email="ada@x.io", name="Ad", limit=10, offset=20))
    assert [c.id for c in result] == [5, 6]
    assert result[0].country_code == "ES"
    assert result[1].country_code is None
    call = client.calls_to("res.partner", "search_read")[0]
    assert call["domain"] == [["email", "=ilike", "ada@x.io"], ["name", "ilike", "Ad"]]
    assert (call["limit"], call["offset"], call["order"]) == (10, 20, "id asc")
    assert call["fields"] == PARTNER_FIELDS


async def test_search_without_filters_uses_empty_domain(
    repo: OdooCustomerRepository, client: FakeOdooClient
) -> None:
    client.script("res.partner", "search_read", [])
    assert await repo.search(CustomerQuery()) == []
    assert client.calls_to("res.partner", "search_read")[0]["domain"] == []


async def test_search_resolves_unknown_countries_in_one_batch(
    repo: OdooCustomerRepository, client: FakeOdooClient
) -> None:
    client.script(
        "res.partner",
        "search_read",
        [partner(), partner(id=6, country_id=[69, "France"]), partner(id=7)],
    )
    client.script("res.country", "read", [{"id": 68, "code": "ES"}, {"id": 69, "code": "FR"}])
    result = await repo.search(CustomerQuery())
    assert [c.country_code for c in result] == ["ES", "FR", "ES"]
    reads = client.calls_to("res.country", "read")
    assert len(reads) == 1
    assert sorted(reads[0]["ids"]) == [68, 69]


async def test_archive_sets_active_false(
    repo: OdooCustomerRepository, client: FakeOdooClient
) -> None:
    client.script("res.partner", "write", True)
    await repo.archive(5)
    assert client.calls_to("res.partner", "write") == [{"ids": [5], "values": {"active": False}}]
