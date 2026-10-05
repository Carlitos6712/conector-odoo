"""The reusable in-memory endpoint satisfies both ports and behaves like a remote system."""

import pytest

from conector_odoo.domain.errors import RecordRejected, ResourceNotFound
from conector_odoo.domain.ports import RecordEndpoint, RecordSink, RecordSource
from conector_odoo.domain.records import FieldSpec, FieldType, Record, RecordFilter, ResourceSchema
from tests.unit.fakes_records import InMemoryRecordEndpoint

SCHEMA = ResourceSchema(
    name="clients", label="Clients", fields=(FieldSpec("email", FieldType.STRING),)
)


def endpoint(n: int = 0) -> InMemoryRecordEndpoint:
    ep = InMemoryRecordEndpoint({"clients": SCHEMA})
    for i in range(n):
        ep.seed("clients", {"email": f"u{i}@x.com", "group": "a" if i % 2 else "b"})
    return ep


def test_conforms_to_protocols() -> None:
    ep = endpoint()
    assert isinstance(ep, RecordSource)
    assert isinstance(ep, RecordSink)
    assert isinstance(ep, RecordEndpoint)


async def test_describe_and_unknown_resource() -> None:
    ep = endpoint()
    assert await ep.describe("clients") == SCHEMA
    with pytest.raises(ResourceNotFound):
        await ep.describe("nope")
    with pytest.raises(ResourceNotFound):
        await ep.get("nope", "1")


async def test_iter_batches_paginates_in_order() -> None:
    ep = endpoint(5)
    batches = [b async for b in ep.iter_batches("clients", RecordFilter(), 2)]
    assert [len(b) for b in batches] == [2, 2, 1]
    assert [r.id for b in batches for r in b] == ["1", "2", "3", "4", "5"]


async def test_iter_batches_applies_equals_filter() -> None:
    ep = endpoint(4)
    got = [
        r
        async for b in ep.iter_batches("clients", RecordFilter(equals={"group": "a"}), 10)
        for r in b
    ]
    assert [r.id for r in got] == ["2", "4"]


async def test_get_and_sample() -> None:
    ep = endpoint(3)
    assert (await ep.get("clients", "2")) == Record(
        id="2", fields={"email": "u1@x.com", "group": "a"}
    )
    assert await ep.get("clients", "99") is None
    assert [r.id for r in await ep.sample("clients", 2)] == ["1", "2"]


async def test_find_by() -> None:
    ep = endpoint(3)
    found = await ep.find_by("clients", "email", "u2@x.com")
    assert found is not None and found.id == "3"
    assert await ep.find_by("clients", "email", "zz") is None


async def test_create_and_update() -> None:
    ep = endpoint()
    created = await ep.create("clients", {"email": "a@x.com"}, "k1")
    assert created.id == "1"
    updated = await ep.update("clients", "1", {"phone": "5"})
    assert updated.fields == {"email": "a@x.com", "phone": "5"}
    with pytest.raises(ResourceNotFound):
        await ep.update("clients", "9", {})


async def test_idempotency_key_replays_same_record() -> None:
    ep = endpoint()
    first = await ep.create("clients", {"email": "a@x.com"}, "k1")
    again = await ep.create("clients", {"email": "other"}, "k1")
    assert again == first
    assert len(ep.records["clients"]) == 1
    assert ep.create_calls == 2


async def test_rejection_on_demand() -> None:
    ep = endpoint()
    ep.reject_next(RecordRejected("nope", {"email": "bad"}))
    with pytest.raises(RecordRejected):
        await ep.create("clients", {"email": "a"}, "k1")
    # only once; a retry with the same key now succeeds and nothing was stored before
    assert (await ep.create("clients", {"email": "a"}, "k1")).id == "1"
