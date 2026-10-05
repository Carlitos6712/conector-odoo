import httpx
import pytest
import respx

from conector_odoo.domain.errors import RemoteUnavailable
from conector_odoo.domain.records import RecordFilter
from conector_odoo.domain.resources import PaginationConfig, PaginationStrategy
from tests.rest.helpers import BASE, collect, config, endpoint, query

LIST = f"{BASE}/items"


def ids(records: list) -> list[str]:  # type: ignore[type-arg]
    return [r.id for r in records]


def paged(data: list[dict], page_size: int, with_total: bool = True):  # type: ignore[no-untyped-def,type-arg]
    """Server answering ``page``/``page_size`` queries over ``data`` (page size honoured)."""

    def handler(request: httpx.Request) -> httpx.Response:
        q = query(request)
        page, size = int(q["page"]), min(int(q["page_size"]), page_size)
        chunk = data[(page - 1) * size : page * size]
        body: dict = {"data": {"items": chunk}}  # type: ignore[type-arg]
        if with_total:
            body["meta"] = {"pages": -(-len(data) // size)}
        return httpx.Response(200, json=body)

    return handler


PAGE = PaginationConfig(
    strategy=PaginationStrategy.PAGE,
    page_param="page",
    size_param="page_size",
    total_pages_path="meta.pages",
)


def rows(n: int) -> list[dict]:  # type: ignore[type-arg]
    return [{"id": i} for i in range(1, n + 1)]


@respx.mock
async def test_page_strategy_walks_every_page_and_stops_on_total_pages() -> None:
    route = respx.get(LIST).mock(side_effect=paged(rows(5), 2))
    ep = endpoint(config(items_path="data.items", pagination=PAGE))
    assert ids(await collect(ep, size=2)) == ["1", "2", "3", "4", "5"]
    assert route.call_count == 3
    assert query(route.calls[0].request) == {"page": "1", "page_size": "2"}


@respx.mock
async def test_page_total_pages_beats_server_capped_page_size() -> None:
    route = respx.get(LIST).mock(side_effect=paged(rows(6), 2))  # server caps at 2
    ep = endpoint(config(items_path="data.items", pagination=PAGE))
    assert len(await collect(ep, size=5)) == 6
    assert route.call_count == 3


@respx.mock
async def test_page_stops_on_short_page_without_total() -> None:
    route = respx.get(LIST).mock(side_effect=paged(rows(5), 2, with_total=False))
    pagination = PaginationConfig(strategy=PaginationStrategy.PAGE)
    ep = endpoint(config(items_path="data.items", pagination=pagination))
    assert len(await collect(ep, size=2)) == 5
    assert route.call_count == 3  # 2, 2, 1(short) -> no fourth call


@respx.mock
async def test_page_stops_on_empty_page() -> None:
    route = respx.get(LIST).mock(side_effect=paged(rows(4), 2, with_total=False))
    pagination = PaginationConfig(strategy=PaginationStrategy.PAGE)
    ep = endpoint(config(items_path="data.items", pagination=pagination))
    assert len(await collect(ep, size=2)) == 4
    assert route.call_count == 3  # 2, 2, empty


@respx.mock
async def test_page_repeated_page_is_a_loop_error() -> None:
    respx.get(LIST).respond(200, json={"data": {"items": rows(2)}})  # ignores page param
    pagination = PaginationConfig(strategy=PaginationStrategy.PAGE)
    ep = endpoint(config(items_path="data.items", pagination=pagination))
    with pytest.raises(RemoteUnavailable, match="repeat"):
        await collect(ep, size=2)


@respx.mock
async def test_page_max_pages_guard() -> None:
    def endless(request: httpx.Request) -> httpx.Response:
        page = int(query(request)["page"])
        return httpx.Response(200, json={"items": [{"id": page * 10}, {"id": page * 10 + 1}]})

    route = respx.get(LIST).mock(side_effect=endless)
    pagination = PaginationConfig(strategy=PaginationStrategy.PAGE, max_pages=3)
    with pytest.raises(RemoteUnavailable, match="max_pages"):
        await collect(endpoint(config(pagination=pagination)), size=2)
    assert route.call_count == 3


@respx.mock
async def test_offset_strategy_uses_total() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        q = query(request)
        offset, limit = int(q["skip"]), int(q["take"])
        return httpx.Response(200, json={"total": 5, "items": rows(5)[offset : offset + limit]})

    route = respx.get(LIST).mock(side_effect=handler)
    pagination = PaginationConfig(
        strategy=PaginationStrategy.OFFSET,
        offset_param="skip",
        limit_param="take",
        total_path="total",
    )
    assert len(await collect(endpoint(config(pagination=pagination)), size=2)) == 5
    assert route.call_count == 3
    assert query(route.calls[1].request) == {"skip": "2", "take": "2"}


@respx.mock
async def test_offset_stops_on_short_page_without_total() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        q = query(request)
        offset, limit = int(q["offset"]), int(q["limit"])
        return httpx.Response(200, json={"items": rows(3)[offset : offset + limit]})

    route = respx.get(LIST).mock(side_effect=handler)
    pagination = PaginationConfig(strategy=PaginationStrategy.OFFSET)
    assert len(await collect(endpoint(config(pagination=pagination)), size=2)) == 3
    assert route.call_count == 2


@respx.mock
async def test_cursor_strategy_follows_next_cursor_until_null() -> None:
    pages = {
        None: {"items": rows(2), "next": "c2"},
        "c2": {"items": [{"id": 3}, {"id": 4}], "next": "c3"},
        "c3": {"items": [{"id": 5}], "next": None},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=pages[query(request).get("after")])

    route = respx.get(LIST).mock(side_effect=handler)
    pagination = PaginationConfig(
        strategy=PaginationStrategy.CURSOR,
        cursor_param="after",
        next_cursor_path="next",
        limit_param="n",
    )
    ep = endpoint(config(pagination=pagination))
    assert ids(await collect(ep, size=2)) == ["1", "2", "3", "4", "5"]
    assert route.call_count == 3
    assert query(route.calls[0].request) == {"n": "2"}


@respx.mock
async def test_cursor_repeated_cursor_is_a_loop_error() -> None:
    respx.get(LIST).respond(200, json={"items": rows(2), "next": "same"})
    pagination = PaginationConfig(strategy=PaginationStrategy.CURSOR, next_cursor_path="next")
    with pytest.raises(RemoteUnavailable, match="cursor"):
        await collect(endpoint(config(pagination=pagination)), size=2)


@respx.mock
async def test_no_pagination_with_root_array_is_chunked() -> None:
    respx.get(LIST).respond(200, json=rows(5))
    ep = endpoint(config(items_path=""))
    batches = [b async for b in ep.iter_batches("items", RecordFilter(), 2)]
    assert [len(b) for b in batches] == [2, 2, 1]


@respx.mock
async def test_list_response_with_wrong_shape_is_unavailable() -> None:
    respx.get(LIST).respond(200, json={"items": {"not": "a list"}})
    with pytest.raises(RemoteUnavailable, match="items"):
        await collect(endpoint(), size=2)


@respx.mock
async def test_filters_map_to_params_and_unmapped_equals_filter_client_side() -> None:
    route = respx.get(LIST).respond(
        200, json={"items": [{"id": 1, "status": "a", "kind": "x"}, {"id": 2, "status": "a"}]}
    )
    cfg = config(filter_param_map={"status": "state"}, since_param="updated_since")
    from datetime import UTC, datetime

    flt = RecordFilter(
        equals={"status": "a", "kind": "x"},
        since=datetime(2024, 1, 2, tzinfo=UTC),
        raw={"extra": "1"},
    )
    got = await collect(endpoint(cfg), record_filter=flt)
    assert ids(got) == ["1"]  # "kind" has no param: filtered locally
    assert query(route.calls[0].request) == {
        "state": "a",
        "updated_since": "2024-01-02T00:00:00+00:00",
        "extra": "1",
    }


@respx.mock
async def test_loop_guard_also_works_for_records_without_ids() -> None:
    respx.get(LIST).respond(200, json={"items": [{"name": "a"}, {"name": "b"}]})
    pagination = PaginationConfig(strategy=PaginationStrategy.OFFSET, total_path="total")
    with pytest.raises(RemoteUnavailable, match="repeat"):
        await collect(endpoint(config(pagination=pagination)), size=2)
