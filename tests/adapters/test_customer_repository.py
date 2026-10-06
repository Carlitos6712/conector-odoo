import pytest

from conector_odoo.domain.entities import (
    Customer,
    CustomerData,
    CustomerFilter,
    CustomerQuery,
    CustomerUpdate,
)
from conector_odoo.domain.errors import (
    CreatedButUnreadable,
    OdooNotFound,
    OdooUnavailable,
    OdooValidationError,
)
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
    assert client.calls_to("res.partner", "read")[0] == {
        "ids": [5],
        "fields": PARTNER_FIELDS,
        "company_id": None,
    }


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


@pytest.mark.parametrize(
    ("email", "pattern"),
    [
        ("john_doe@x.io", "john\\_doe@x.io"),
        ("100%@x.io", "100\\%@x.io"),
        ("a\\b@x.io", "a\\\\b@x.io"),
    ],
)
async def test_search_escapes_like_wildcards_in_the_email_pattern(
    repo: OdooCustomerRepository, client: FakeOdooClient, email: str, pattern: str
) -> None:
    client.script("res.partner", "search_read", [])
    await repo.search(CustomerQuery(email=email))
    assert client.calls_to("res.partner", "search_read")[0]["domain"] == [
        ["email", "=ilike", pattern]
    ]


async def test_search_name_is_passed_raw_because_odoo_escapes_ilike_itself(
    repo: OdooCustomerRepository, client: FakeOdooClient
) -> None:
    client.script("res.partner", "search_read", [])
    await repo.search(CustomerQuery(name="50%_off"))
    assert client.calls_to("res.partner", "search_read")[0]["domain"] == [
        ["name", "ilike", "50%_off"]
    ]


async def test_create_read_back_failure_reports_the_created_customer_id(
    repo: OdooCustomerRepository, client: FakeOdooClient
) -> None:
    client.script("res.partner", "create", 5)
    client.script("res.partner", "read", OdooUnavailable("boom"))
    with pytest.raises(CreatedButUnreadable) as info:
        await repo.create(CustomerData(name="Ada"))
    assert (info.value.model, info.value.record_id) == ("res.partner", 5)
    assert "customer 5 was created" in str(info.value)


async def test_iter_batches_streams_keyset_batches_with_filters(
    repo: OdooCustomerRepository, client: FakeOdooClient
) -> None:
    client.script(
        "res.partner",
        "iter_search_read",
        [partner(), partner(id=6)],
        [partner(id=7)],
    )
    client.script("res.country", "read", [{"id": 68, "code": "ES"}])
    batches = [
        b
        async for b in repo.iter_batches(
            CustomerFilter(email="a_b@x.io", name="Ad", active=False), batch_size=2
        )
    ]
    assert [[c.id for c in b] for b in batches] == [[5, 6], [7]]
    assert all(c.country_code == "ES" for b in batches for c in b)
    call = client.calls_to("res.partner", "iter_search_read")[0]
    assert call["domain"] == [
        ["email", "=ilike", "a\\_b@x.io"],
        ["name", "ilike", "Ad"],
        ["active", "=", False],
    ]
    assert call["batch_size"] == 2
    assert call["fields"] == PARTNER_FIELDS


async def test_iter_batches_uses_the_configured_default_batch_size(
    client: FakeOdooClient,
) -> None:
    repo = OdooCustomerRepository(client, batch_size=123)  # type: ignore[arg-type]
    client.script("res.partner", "iter_search_read", [partner(country_id=False)])
    async for _ in repo.iter_batches(CustomerFilter()):
        pass
    call = client.calls_to("res.partner", "iter_search_read")[0]
    assert call["batch_size"] == 123
    assert call["domain"] == []


async def test_iter_batches_resolves_countries_once_per_batch_without_n_plus_one(
    repo: OdooCustomerRepository, client: FakeOdooClient
) -> None:
    client.script(
        "res.partner",
        "iter_search_read",
        [partner(id=1), partner(id=2, country_id=[69, "France"]), partner(id=3)],
        [partner(id=4), partner(id=5, country_id=[70, "Italy"])],
        [partner(id=6)],
    )
    client.script(
        "res.country",
        "read",
        [{"id": 68, "code": "ES"}, {"id": 69, "code": "FR"}],
        [{"id": 70, "code": "IT"}],
    )
    codes = [c.country_code async for b in repo.iter_batches(CustomerFilter()) for c in b]
    assert codes == ["ES", "FR", "ES", "ES", "IT", "ES"]
    reads = client.calls_to("res.country", "read")
    assert [r["ids"] for r in reads] == [[68, 69], [70]]


async def test_iter_batches_propagates_mid_stream_errors(
    repo: OdooCustomerRepository, client: FakeOdooClient
) -> None:
    client.script(
        "res.partner",
        "iter_search_read",
        [partner(country_id=False)],
        OdooUnavailable("down"),
    )
    seen: list[int] = []
    with pytest.raises(OdooUnavailable):
        async for batch in repo.iter_batches(CustomerFilter()):
            seen.extend(c.id or 0 for c in batch)
    assert seen == [5]


async def test_find_by_emails_uses_one_case_insensitive_or_search(
    repo: OdooCustomerRepository, client: FakeOdooClient
) -> None:
    client.script(
        "res.partner",
        "search_read",
        [
            partner(id=9, email="Ada@X.io"),
            partner(id=5, email="ada@x.io"),
            partner(id=7, email="b_@x.io"),
        ],
    )
    client.script("res.country", "read", [{"id": 68, "code": "ES"}])
    found = await repo.find_by_emails(["ada@x.io", "b_@x.io"])
    assert set(found) == {"ada@x.io", "b_@x.io"}
    assert found["ada@x.io"].id == 9  # first row wins (rows come ordered by id asc from Odoo)
    assert found["ada@x.io"].country_code == "ES"
    calls = client.calls_to("res.partner", "search_read")
    assert len(calls) == 1
    assert calls[0]["domain"] == [
        "|",
        ["email", "=ilike", "ada@x.io"],
        ["email", "=ilike", "b\\_@x.io"],
    ]
    assert calls[0]["order"] == "id asc"
    assert calls[0]["fields"] == PARTNER_FIELDS
    assert len(client.calls_to("res.country", "read")) == 1


async def test_find_by_emails_chunks_large_lookups_without_per_email_calls(
    repo: OdooCustomerRepository, client: FakeOdooClient
) -> None:
    emails = [f"u{i}@x.io" for i in range(250)]
    client.script("res.partner", "search_read", [], [], [])
    assert await repo.find_by_emails(emails) == {}
    calls = client.calls_to("res.partner", "search_read")
    assert len(calls) == 3  # 100 + 100 + 50
    assert calls[0]["domain"].count("|") == 99
    assert calls[2]["domain"].count("|") == 49


async def test_find_by_emails_single_email_has_no_or_operator(
    repo: OdooCustomerRepository, client: FakeOdooClient
) -> None:
    client.script("res.partner", "search_read", [])
    await repo.find_by_emails(["a@x.io"])
    assert client.calls_to("res.partner", "search_read")[0]["domain"] == [
        ["email", "=ilike", "a@x.io"]
    ]


async def test_find_by_emails_empty_makes_no_call(
    repo: OdooCustomerRepository, client: FakeOdooClient
) -> None:
    assert await repo.find_by_emails([]) == {}
    assert client.calls == []


async def test_create_many_resolves_countries_and_creates_in_one_call(
    repo: OdooCustomerRepository, client: FakeOdooClient
) -> None:
    client.script("res.country", "search_read", [{"id": 68, "code": "ES"}])
    client.script("res.partner", "create_many", [11, 12])
    ids = await repo.create_many(
        [
            CustomerData(name="A", email="a@x.io", country_code="es"),
            CustomerData(name="B", country_code="ES", is_company=True),
        ]
    )
    assert ids == [11, 12]
    assert len(client.calls_to("res.country", "search_read")) == 1  # cached across items
    assert client.calls_to("res.partner", "create_many") == [
        {
            "vals_list": [
                {"name": "A", "email": "a@x.io", "country_id": 68, "is_company": False},
                {"name": "B", "country_id": 68, "is_company": True},
            ],
            "chunk_size": 100,
        }
    ]


async def test_create_many_with_nothing_makes_no_call(
    repo: OdooCustomerRepository, client: FakeOdooClient
) -> None:
    assert await repo.create_many([]) == []
    assert client.calls == []


async def test_known_country_codes_uses_one_lookup_and_the_cache(
    repo: OdooCustomerRepository, client: FakeOdooClient
) -> None:
    client.script("res.country", "search_read", [{"id": 68, "code": "ES"}])
    assert await repo.known_country_codes({"ES", "ZZ"}) == {"ES"}
    call = client.calls_to("res.country", "search_read")[0]
    assert call["domain"] == [["code", "in", ["ES", "ZZ"]]]
    assert await repo.known_country_codes({"ES"}) == {"ES"}  # cached: no second call
    assert len(client.calls_to("res.country", "search_read")) == 1
    assert await repo.known_country_codes(set()) == set()


async def test_apply_update_writes_without_reading_back(
    repo: OdooCustomerRepository, client: FakeOdooClient
) -> None:
    client.script("res.partner", "write", True)
    await repo.apply_update(5, CustomerUpdate(city="Sevilla"))
    assert client.calls_to("res.partner", "write") == [{"ids": [5], "values": {"city": "Sevilla"}}]
    assert client.calls_to("res.partner", "read") == []


async def test_apply_update_with_no_changes_makes_no_call(
    repo: OdooCustomerRepository, client: FakeOdooClient
) -> None:
    await repo.apply_update(5, CustomerUpdate())
    assert client.calls == []
