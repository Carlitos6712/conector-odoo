import asyncio
from typing import Any

import pytest

from conector_odoo.domain.errors import (
    BatchPartiallyApplied,
    OdooAuthError,
    OdooUnavailable,
    OdooValidationError,
)
from conector_odoo.infrastructure.odoo.client import OdooClient

Call = tuple[str, str, list[Any], dict[str, Any]]


class RecordingTransport:
    """Serves ``search_read`` from a sorted id list, honouring the keyset domain and limit."""

    def __init__(self, ids: list[int] | None = None) -> None:
        self.ids = sorted(ids or [])
        self.calls: list[Call] = []
        self.create_results: list[Any] = []
        self.next_id = 1000

    async def authenticate(self) -> int:
        return 7

    async def execute_kw(
        self, model: str, method: str, args: list[Any], kwargs: dict[str, Any] | None = None
    ) -> Any:
        kw = dict(kwargs or {})
        self.calls.append((model, method, args, kw))
        if method == "search_read":
            domain = args[0]
            floor = max((t[2] for t in domain if t[:2] == ["id", ">"]), default=0)
            rows = [{"id": i, "name": f"r{i}"} for i in self.ids if i > floor]
            return rows[: kw.get("limit")]
        if method == "read":
            return [{"id": i, "name": f"r{i}"} for i in reversed(args[0])]  # scrambled order
        if method == "create":
            if self.create_results:
                item = self.create_results.pop(0)
                if isinstance(item, BaseException):
                    raise item
                return item
            created = list(range(self.next_id, self.next_id + len(args[0])))
            self.next_id += len(args[0])
            return created
        return True

    async def aclose(self) -> None:
        return None


def make(ids: list[int] | None = None) -> tuple[OdooClient, RecordingTransport]:
    transport = RecordingTransport(ids)
    return OdooClient(transport), transport


async def collect(client: OdooClient, **kwargs: Any) -> list[list[dict[str, Any]]]:
    return [
        batch
        async for batch in client.iter_search_read("res.partner", [["active", "=", True]], **kwargs)
    ]


async def test_iter_search_read_uses_keyset_pagination_across_batches() -> None:
    client, transport = make(list(range(1, 8)))  # 7 rows, batch 3 -> 3, 3, 1
    batches = await collect(client, fields=["name"], batch_size=3)
    assert [[r["id"] for r in b] for b in batches] == [[1, 2, 3], [4, 5, 6], [7]]
    domains = [c[2][0] for c in transport.calls]
    assert domains[0] == [["active", "=", True]]
    assert domains[1] == [["active", "=", True], ["id", ">", 3]]
    assert domains[2] == [["active", "=", True], ["id", ">", 6]]
    for _model, _method, _args, kw in transport.calls:
        assert kw["limit"] == 3
        assert kw["order"] == "id asc"
        assert "offset" not in kw
        assert "id" in kw["fields"]


async def test_iter_search_read_does_one_extra_call_when_last_batch_is_full() -> None:
    client, transport = make(list(range(1, 7)))  # 6 rows, batch 3 -> 3, 3, then empty
    batches = await collect(client, batch_size=3)
    assert [len(b) for b in batches] == [3, 3]
    assert len(transport.calls) == 3


async def test_iter_search_read_empty_result_yields_nothing() -> None:
    client, transport = make([])
    assert await collect(client, batch_size=3) == []
    assert len(transport.calls) == 1


async def test_iter_search_read_without_fields_reads_all_fields() -> None:
    client, transport = make([1])
    await collect(client, batch_size=3)
    assert "fields" not in transport.calls[0][3]


@pytest.mark.parametrize("size", [0, -1, 5001])
async def test_iter_search_read_validates_batch_size(size: int) -> None:
    client, transport = make([1])
    with pytest.raises(OdooValidationError):
        await collect(client, batch_size=size)
    assert transport.calls == []


async def test_iter_search_read_passes_company_and_context() -> None:
    client, transport = make([1])
    async for _ in client.iter_search_read(
        "res.partner", [], batch_size=2, company_id=4, context={"lang": "es_ES"}
    ):
        pass
    context = transport.calls[0][3]["context"]
    assert context["company_id"] == 4
    assert context["lang"] == "es_ES"


async def test_read_many_chunks_preserves_input_order_and_skips_missing() -> None:
    client, transport = make()
    rows = await client.read_many("res.partner", [5, 3, 99, 1, 4], ["name"], chunk_size=2)
    # the transport returns every chunk reversed and knows every id: order must follow the input
    assert [r["id"] for r in rows] == [5, 3, 99, 1, 4]
    assert [c[2][0] for c in transport.calls] == [[5, 3], [99, 1], [4]]


async def test_read_many_skips_ids_odoo_does_not_return() -> None:
    client, transport = make()

    async def execute(model: str, method: str, args: list[Any], kwargs: Any = None) -> Any:
        return [{"id": i} for i in args[0] if i != 99]

    transport.execute_kw = execute  # type: ignore[method-assign]
    rows = await client.read_many("res.partner", [2, 99, 1], None, chunk_size=10)
    assert [r["id"] for r in rows] == [2, 1]


async def test_read_many_empty_makes_no_call() -> None:
    client, transport = make()
    assert await client.read_many("res.partner", [], ["name"]) == []
    assert transport.calls == []


async def test_read_many_validates_chunk_size() -> None:
    client, _ = make()
    with pytest.raises(OdooValidationError):
        await client.read_many("res.partner", [1], None, chunk_size=0)


@pytest.mark.parametrize(
    ("count", "chunk", "sizes"),
    [
        (0, 100, []),
        (1, 100, [1]),
        (100, 100, [100]),
        (101, 100, [100, 1]),
        (250, 100, [100, 100, 50]),
    ],
)
async def test_create_many_chunk_boundaries(count: int, chunk: int, sizes: list[int]) -> None:
    client, transport = make()
    values = [{"name": f"n{i}"} for i in range(count)]
    ids = await client.create_many("res.partner", values, chunk_size=chunk)
    assert [len(c[2][0]) for c in transport.calls] == sizes
    assert len(ids) == count
    assert ids == sorted(ids)
    assert all(isinstance(i, int) for i in ids)


async def test_create_many_sends_the_values_in_order() -> None:
    client, transport = make()
    await client.create_many(
        "res.partner", [{"name": "a"}, {"name": "b"}, {"name": "c"}], chunk_size=2
    )
    assert transport.calls[0][2] == [[{"name": "a"}, {"name": "b"}]]
    assert transport.calls[1][2] == [[{"name": "c"}]]


async def test_create_many_rejects_a_malformed_result() -> None:
    client, transport = make()
    transport.create_results = [[1]]  # two values, one id
    with pytest.raises(OdooUnavailable):
        await client.create_many("res.partner", [{"name": "a"}, {"name": "b"}])


async def test_create_many_partial_failure_carries_created_ids() -> None:
    client, transport = make()
    transport.create_results = [[11, 12], [13, 14], OdooUnavailable("timeout")]
    with pytest.raises(BatchPartiallyApplied) as info:
        await client.create_many("res.partner", [{"name": str(i)} for i in range(5)], chunk_size=2)
    error = info.value
    assert error.created_ids == [11, 12, 13, 14]
    assert error.failed_chunk == 2
    assert isinstance(error.__cause__, OdooUnavailable)
    assert "timeout" in str(error)
    assert len(transport.calls) == 3  # never retried, never continued


async def test_create_many_first_chunk_failure_is_not_partial() -> None:
    client, transport = make()
    transport.create_results = [OdooValidationError("bad")]
    with pytest.raises(OdooValidationError):
        await client.create_many("res.partner", [{"name": "a"}], chunk_size=1)


async def test_create_many_validates_chunk_size() -> None:
    client, transport = make()
    with pytest.raises(OdooValidationError):
        await client.create_many("res.partner", [{"name": "a"}], chunk_size=0)
    assert transport.calls == []


async def test_single_create_still_returns_an_int() -> None:
    client, transport = make()
    transport.create_results = [[42]]
    assert await client.create("res.partner", {"name": "a"}) == 42
    transport.create_results = [43]
    assert await client.create("res.partner", {"name": "a"}) == 43


async def test_write_many_chunks_the_ids_with_the_same_values() -> None:
    client, transport = make()
    assert await client.write_many("res.partner", [1, 2, 3, 4, 5], {"active": False}, chunk_size=2)
    assert [c[2] for c in transport.calls] == [
        [[1, 2], {"active": False}],
        [[3, 4], {"active": False}],
        [[5], {"active": False}],
    ]


async def test_write_many_empty_makes_no_call() -> None:
    client, transport = make()
    assert await client.write_many("res.partner", [], {"active": False}) is True
    assert transport.calls == []


class GatedTransport:
    """Counts in-flight calls; every call waits for ``gate`` before returning."""

    def __init__(self) -> None:
        self.gate = asyncio.Event()
        self.in_flight = 0
        self.max_in_flight = 0
        self.completed = 0

    async def authenticate(self) -> int:
        return 1

    async def execute_kw(
        self, model: str, method: str, args: list[Any], kwargs: dict[str, Any] | None = None
    ) -> Any:
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await self.gate.wait()
        finally:
            self.in_flight -= 1
        self.completed += 1
        return 0

    async def aclose(self) -> None:
        return None


async def test_semaphore_caps_concurrent_in_flight_calls() -> None:
    transport = GatedTransport()
    client = OdooClient(transport, max_concurrency=3)
    tasks = [asyncio.create_task(client.search_count("res.partner", [])) for _ in range(10)]
    for _ in range(20):
        await asyncio.sleep(0)
    assert transport.in_flight == 3  # the other seven wait on the semaphore
    transport.gate.set()
    await asyncio.gather(*tasks)
    assert transport.max_in_flight == 3
    assert transport.completed == 10


async def test_default_concurrency_is_eight() -> None:
    transport = GatedTransport()
    client = OdooClient(transport)
    tasks = [asyncio.create_task(client.search_count("res.partner", [])) for _ in range(20)]
    for _ in range(20):
        await asyncio.sleep(0)
    assert transport.in_flight == 8
    transport.gate.set()
    await asyncio.gather(*tasks)


@pytest.mark.parametrize("value", [0, -1])
def test_max_concurrency_must_be_positive(value: int) -> None:
    with pytest.raises(ValueError, match="max_concurrency"):
        OdooClient(GatedTransport(), max_concurrency=value)


async def test_reauthentication_does_not_deadlock_with_a_single_slot() -> None:
    transport = RecordingTransport([1])
    original = transport.execute_kw
    failed = False

    async def flaky(model: str, method: str, args: list[Any], kwargs: Any = None) -> Any:
        nonlocal failed
        if not failed:
            failed = True
            raise OdooAuthError("expired")
        return await original(model, method, args, kwargs)

    transport.execute_kw = flaky  # type: ignore[method-assign]
    client = OdooClient(transport, max_concurrency=1)
    result = await asyncio.wait_for(client.search_count("res.partner", []), timeout=2)
    assert result == 1
