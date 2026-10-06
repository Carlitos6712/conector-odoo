import pytest

from conector_odoo.application.customers import BulkUpsertCustomers
from conector_odoo.domain.entities import (
    BulkUpsertResult,
    Customer,
    CustomerUpsert,
    RejectedItem,
)
from conector_odoo.domain.errors import (
    BatchPartiallyApplied,
    OdooUnavailable,
    OdooValidationError,
)
from tests.unit.fakes import FakeCustomerRepository


def item(name: str = "N", email: str | None = None, **fields: object) -> CustomerUpsert:
    return CustomerUpsert(name=name, email=email, **fields)  # type: ignore[arg-type]


def statuses(result: BulkUpsertResult) -> list[tuple[int, str, int | None]]:
    return [(r.index, r.status, r.id) for r in result.results]


def seed(repo: FakeCustomerRepository, **kw: object) -> None:
    repo.items[repo._next_id] = Customer(id=repo._next_id, **kw)  # type: ignore[arg-type]
    repo._next_id += 1


async def test_mixed_create_update_and_failed() -> None:
    repo = FakeCustomerRepository()
    seed(repo, name="Old", email="old@x.io")
    items = [
        item("New", "new@x.io"),
        item("Renamed", "old@x.io"),
        RejectedItem("email: not a valid email address"),
        item("   ", "blank@x.io"),
        item("NoMail"),
    ]
    result = await BulkUpsertCustomers(repo).execute(items)
    assert (result.created, result.updated, result.failed) == (2, 1, 2)
    assert statuses(result) == [
        (0, "created", 2),
        (1, "updated", 1),
        (2, "failed", None),
        (3, "failed", None),
        (4, "created", 3),
    ]
    assert result.results[2].error == "email: not a valid email address"
    assert result.results[3].error == "customer name must not be blank"
    assert repo.items[1].name == "Renamed"


async def test_existing_partners_match_case_insensitively() -> None:
    repo = FakeCustomerRepository()
    seed(repo, name="Ada", email="Ada@X.io")
    result = await BulkUpsertCustomers(repo).execute([item("Ada L.", "  ADA@x.IO ")])
    assert statuses(result) == [(0, "updated", 1)]
    assert len(repo.items) == 1
    assert repo.find_calls == [["ada@x.io"]]


async def test_new_emails_are_stored_normalized() -> None:
    repo = FakeCustomerRepository()
    await BulkUpsertCustomers(repo).execute([item("Bob", " Bob@X.IO ")])
    assert repo.create_many_calls[0][0].email == "bob@x.io"


async def test_duplicate_emails_in_the_payload_fail_after_the_first() -> None:
    repo = FakeCustomerRepository()
    items = [item("A", "dup@x.io"), item("B", "DUP@x.io "), item("C", "other@x.io")]
    result = await BulkUpsertCustomers(repo).execute(items)
    assert statuses(result) == [(0, "created", 1), (1, "failed", None), (2, "created", 2)]
    error = result.results[1].error or ""
    assert "duplicate email" in error
    assert "index 0" in error


async def test_items_without_email_are_always_created() -> None:
    repo = FakeCustomerRepository()
    result = await BulkUpsertCustomers(repo).execute([item("A"), item("A"), item("B", "  ")])
    assert [r.status for r in result.results] == ["created"] * 3
    assert repo.find_calls == []  # nothing to look up


async def test_updates_write_only_the_provided_fields() -> None:
    repo = FakeCustomerRepository()
    seed(repo, name="Ada", email="a@x.io", phone="1", city="Madrid", is_company=True)
    await BulkUpsertCustomers(repo).execute([item("Ada", "a@x.io", city="Sevilla")])
    assert repo.applied_updates == [(1, {"city": "Sevilla"})]  # same name, no phone, no flag
    assert repo.items[1].phone == "1"
    assert repo.items[1].is_company is True


async def test_is_company_is_written_only_when_provided() -> None:
    repo = FakeCustomerRepository()
    seed(repo, name="Ada", email="a@x.io", is_company=False)
    await BulkUpsertCustomers(repo).execute([item("Ada", "a@x.io", is_company=True)])
    assert repo.applied_updates == [(1, {"is_company": True})]


async def test_an_unchanged_record_is_reported_updated_without_a_write() -> None:
    repo = FakeCustomerRepository()
    seed(repo, name="Ada", email="a@x.io", city="Madrid", country_code="ES")
    result = await BulkUpsertCustomers(repo).execute(
        [item("Ada", "A@x.io", city="Madrid", country_code="es")]
    )
    assert statuses(result) == [(0, "updated", 1)]
    assert repo.applied_updates == []


async def test_unknown_country_fails_only_that_item() -> None:
    repo = FakeCustomerRepository()
    seed(repo, name="Old", email="old@x.io")
    items = [
        item("Ok", "ok@x.io", country_code="ES"),
        item("Bad", "bad@x.io", country_code="zz"),
        item("BadUpdate", "old@x.io", country_code="ZZ"),
    ]
    result = await BulkUpsertCustomers(repo).execute(items)
    assert [r.status for r in result.results] == ["created", "failed", "failed"]
    assert "unknown country code 'ZZ'" in (result.results[1].error or "")
    assert repo.applied_updates == []


async def test_a_failed_item_does_not_claim_its_email() -> None:
    repo = FakeCustomerRepository()
    items = [item("Bad", "x@x.io", country_code="ZZ"), item("Good", "x@x.io")]
    result = await BulkUpsertCustomers(repo).execute(items)
    assert [r.status for r in result.results] == ["failed", "created"]


async def test_the_repository_is_called_in_batches_not_per_item() -> None:
    repo = FakeCustomerRepository()
    for i in range(20):
        seed(repo, name=f"E{i}", email=f"e{i}@x.io")
    items = [item(f"E{i}!", f"e{i}@x.io") for i in range(20)]
    items += [item(f"N{i}", f"n{i}@x.io") for i in range(30)]
    result = await BulkUpsertCustomers(repo).execute(items)
    assert (result.created, result.updated, result.failed) == (30, 20, 0)
    assert len(repo.find_calls) == 1
    assert len(repo.find_calls[0]) == 50
    assert len(repo.create_many_calls) == 1
    assert "create" not in repo.calls  # no per-item create
    assert len(repo.applied_updates) == 20


async def test_partial_batch_failure_keeps_created_ids_and_fails_the_rest() -> None:
    repo = FakeCustomerRepository()
    repo.create_many_error = BatchPartiallyApplied([10, 11], 1, "chunk 1 failed: timeout")
    items = [item(f"N{i}", f"n{i}@x.io") for i in range(5)]
    result = await BulkUpsertCustomers(repo).execute(items)
    assert statuses(result) == [
        (0, "created", 10),
        (1, "created", 11),
        (2, "failed", None),
        (3, "failed", None),
        (4, "failed", None),
    ]
    assert (result.created, result.failed) == (2, 3)
    error = result.results[2].error or ""
    assert "chunk 1 failed: timeout" in error
    assert "verify" in error


async def test_a_failed_create_does_not_stop_the_updates() -> None:
    repo = FakeCustomerRepository()
    seed(repo, name="Old", email="old@x.io")
    repo.create_many_error = OdooUnavailable("down")
    result = await BulkUpsertCustomers(repo).execute(
        [item("New", "n@x.io"), item("Upd", "old@x.io")]
    )
    assert statuses(result) == [(0, "failed", None), (1, "updated", 1)]
    assert result.results[0].error == "down"


async def test_a_failed_update_does_not_abort_the_batch() -> None:
    repo = FakeCustomerRepository()
    seed(repo, name="A", email="a@x.io")
    seed(repo, name="B", email="b@x.io")
    repo.apply_update_errors[1] = OdooValidationError("invalid vat")
    items = [item("A2", "a@x.io"), item("B2", "b@x.io"), item("C", "c@x.io")]
    result = await BulkUpsertCustomers(repo).execute(items)
    assert statuses(result) == [(0, "failed", None), (1, "updated", 2), (2, "created", 3)]
    assert result.results[0].error == "invalid vat"


async def test_only_email_matching_is_supported() -> None:
    with pytest.raises(OdooValidationError):
        await BulkUpsertCustomers(FakeCustomerRepository()).execute([item()], match_by="vat")


async def test_empty_input_does_nothing() -> None:
    repo = FakeCustomerRepository()
    result = await BulkUpsertCustomers(repo).execute([])
    assert (result.created, result.updated, result.failed, result.results) == (0, 0, 0, [])
    assert repo.find_calls == [] and repo.create_many_calls == []
