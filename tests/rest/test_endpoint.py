import json

import httpx
import pytest
import respx

from conector_odoo.domain.errors import RecordRejected, ResourceNotFound
from conector_odoo.domain.ports import RecordEndpoint
from conector_odoo.domain.records import FieldSpec, FieldType
from conector_odoo.domain.resources import EndpointSpec, PaginationConfig, PaginationStrategy
from conector_odoo.infrastructure.rest.endpoint import RestRecordEndpoint
from tests.rest.helpers import BASE, StaticConfigs, config, endpoint, http_client, query

LIST = f"{BASE}/items"


def test_adapter_satisfies_the_domain_ports() -> None:
    assert isinstance(endpoint(), RecordEndpoint)


@respx.mock
async def test_get_returns_a_record_using_item_path() -> None:
    respx.get(f"{LIST}/a%2Fb").respond(200, json={"data": {"id": "a/b", "name": "N"}})
    rec = await endpoint(config(item_path="data")).get("items", "a/b")
    assert rec is not None
    assert (rec.id, rec.get("name")) == ("a/b", "N")


@respx.mock
async def test_get_missing_record_is_none() -> None:
    respx.get(f"{LIST}/9").respond(404)
    assert await endpoint().get("items", "9") is None


@respx.mock
async def test_unknown_resource_endpoint_404_on_list_is_resource_not_found() -> None:
    respx.get(LIST).respond(404)
    with pytest.raises(ResourceNotFound):
        await endpoint().sample("items", 1)


async def test_unknown_resource_name_comes_from_the_provider() -> None:
    with pytest.raises(ResourceNotFound):
        await endpoint().get("nope", "1")


@respx.mock
async def test_sample_returns_at_most_limit_records() -> None:
    route = respx.get(LIST).respond(200, json={"items": [{"id": i} for i in range(5)]})
    got = await endpoint().sample("items", 3)
    assert [r.id for r in got] == ["0", "1", "2"]
    assert route.call_count == 1


@respx.mock
async def test_find_by_uses_the_filter_param_when_mapped() -> None:
    route = respx.get(LIST).respond(
        200, json={"items": [{"id": 7, "email": "a@x.test"}, {"id": 8, "email": "other"}]}
    )
    ep = endpoint(config(filter_param_map={"email": "email"}))
    rec = await ep.find_by("items", "email", "a@x.test")
    assert rec is not None
    assert rec.id == "7"
    assert query(route.calls[0].request)["email"] == "a@x.test"


@respx.mock
async def test_find_by_without_filter_param_scans_client_side_across_pages() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        page = int(query(request)["page"])
        data = {1: [{"id": 1, "sku": "a"}], 2: [{"id": 2, "sku": "b"}], 3: []}[page]
        return httpx.Response(200, json={"items": data})

    route = respx.get(LIST).mock(side_effect=handler)
    pagination = PaginationConfig(strategy=PaginationStrategy.PAGE, size_param="page_size")
    ep = RestRecordEndpoint(
        http_client(), StaticConfigs(config(pagination=pagination)), scan_batch_size=1
    )
    rec = await ep.find_by("items", "sku", "b")
    assert rec is not None
    assert rec.id == "2"
    assert route.call_count == 2  # stops as soon as it finds it
    assert await ep.find_by("items", "sku", "zzz") is None


@respx.mock
async def test_create_sends_json_and_idempotency_key_and_returns_record() -> None:
    route = respx.post(LIST).respond(201, json={"id": 11, "name": "N"})
    rec = await endpoint().create("items", {"name": "N"}, "key-1")
    request = route.calls.last.request
    assert json.loads(request.content) == {"name": "N"}
    assert request.headers["Idempotency-Key"] == "key-1"
    assert rec.id == "11"


@respx.mock
async def test_create_replay_sends_the_same_key() -> None:
    route = respx.post(LIST).respond(201, json={"id": 11})
    ep = endpoint()
    await ep.create("items", {"name": "N"}, "key-1")
    await ep.create("items", {"name": "N"}, "key-1")
    assert {c.request.headers["Idempotency-Key"] for c in route.calls} == {"key-1"}


@respx.mock
async def test_create_without_response_body_keeps_sent_fields() -> None:
    respx.post(LIST).respond(204)
    rec = await endpoint().create("items", {"name": "N"}, "k")
    assert rec.id is None
    assert rec.get("name") == "N"


@respx.mock
async def test_create_rejection_carries_field_errors() -> None:
    respx.post(LIST).respond(422, json={"detail": [{"loc": ["body", "name"], "msg": "required"}]})
    with pytest.raises(RecordRejected) as info:
        await endpoint().create("items", {}, "k")
    assert info.value.field_errors == {"name": "required"}


async def test_create_unsupported_resource_is_rejected() -> None:
    with pytest.raises(RecordRejected, match="create"):
        await endpoint(config(create_endpoint=None)).create("items", {}, "k")


@respx.mock
async def test_update_patches_the_item_url() -> None:
    route = respx.patch(f"{LIST}/5").respond(200, json={"id": 5, "name": "New"})
    rec = await endpoint().update("items", "5", {"name": "New"})
    assert json.loads(route.calls.last.request.content) == {"name": "New"}
    assert rec.get("name") == "New"


@respx.mock
async def test_update_missing_record_is_resource_not_found() -> None:
    respx.patch(f"{LIST}/5").respond(404)
    with pytest.raises(ResourceNotFound):
        await endpoint().update("items", "5", {})


async def test_describe_uses_configured_schema_fields() -> None:
    fields = (FieldSpec("name", FieldType.STRING, required=True),)
    schema = await endpoint(config(schema_fields=fields, id_field="uuid")).describe("items")
    assert (schema.name, schema.label, schema.id_field) == ("items", "Items", "uuid")
    assert schema.fields == fields


@respx.mock
async def test_describe_infers_fields_from_a_sample_record() -> None:
    sample = {
        "id": 1,
        "name": "x",
        "active": True,
        "score": 1.5,
        "born": "2020-05-01",
        "seen": "2024-01-02T10:00:00Z",
        "address": {"city": "c"},
        "tags": ["a"],
        "nothing": None,
    }
    respx.get(LIST).respond(200, json={"items": [sample]})
    schema = await endpoint().describe("items")
    types = {f.name: f.type for f in schema.fields}
    assert types == {
        "id": FieldType.INTEGER,
        "name": FieldType.STRING,
        "active": FieldType.BOOLEAN,
        "score": FieldType.NUMBER,
        "born": FieldType.DATE,
        "seen": FieldType.DATETIME,
        "address": FieldType.OBJECT,
        "tags": FieldType.ARRAY,
        "nothing": FieldType.UNKNOWN,
    }


@respx.mock
async def test_describe_without_schema_or_data_is_empty() -> None:
    respx.get(LIST).respond(200, json={"items": []})
    assert (await endpoint().describe("items")).fields == ()


PAGED = PaginationConfig(
    strategy=PaginationStrategy.PAGE,
    page_param="page",
    size_param="page_size",
    total_pages_path="total_pages",
)


def _pages(rows: list[dict[str, int]], size: int):  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        page = int(query(request)["page"])
        chunk = rows[(page - 1) * size : page * size]
        return httpx.Response(200, json={"items": chunk, "total_pages": -(-len(rows) // size)})

    return handler


@respx.mock
async def test_get_without_get_endpoint_falls_back_to_the_paginated_list() -> None:
    respx.get(LIST).mock(side_effect=_pages([{"id": i} for i in range(1, 6)], 2))
    ep = endpoint(config(get_endpoint=None, pagination=PAGED))
    rec = await ep.get("items", "5")
    assert rec is not None and rec.id == "5"


@respx.mock
async def test_get_fallback_returns_none_when_the_id_is_not_listed() -> None:
    respx.get(LIST).mock(side_effect=_pages([{"id": 1}, {"id": 2}], 2))
    assert await endpoint(config(get_endpoint=None, pagination=PAGED)).get("items", "9") is None


@respx.mock
async def test_get_fallback_matches_a_custom_id_field() -> None:
    respx.get(LIST).respond(200, json={"items": [{"uuid": "u1"}, {"uuid": "u2"}]})
    rec = await endpoint(config(get_endpoint=None, id_field="uuid")).get("items", "u2")
    assert rec is not None and rec.id == "u2"


@respx.mock
async def test_configured_get_endpoint_keeps_priority_over_the_list() -> None:
    list_route = respx.get(LIST).respond(200, json={"items": []})
    respx.get(f"{LIST}/7").respond(200, json={"id": 7})
    rec = await endpoint().get("items", "7")
    assert rec is not None and rec.id == "7"
    assert not list_route.called


async def test_delete_without_a_delete_endpoint_is_rejected() -> None:
    with pytest.raises(RecordRejected, match="does not support delete"):
        await endpoint().delete("items", "1")


@respx.mock
async def test_delete_calls_the_item_url() -> None:
    route = respx.delete(f"{LIST}/a%2Fb").respond(204)
    cfg = config(delete_endpoint=EndpointSpec("DELETE", "/items/{id}"))
    assert await endpoint(cfg).delete("items", "a/b") is None
    assert route.call_count == 1


@respx.mock
async def test_delete_missing_record_is_resource_not_found() -> None:
    respx.delete(f"{LIST}/5").respond(404)
    cfg = config(delete_endpoint=EndpointSpec("DELETE", "/items/{id}"))
    with pytest.raises(ResourceNotFound):
        await endpoint(cfg).delete("items", "5")
