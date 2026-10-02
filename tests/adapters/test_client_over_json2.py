"""``OdooClient`` helpers driven end-to-end through ``Json2Transport`` (respx at the HTTP edge)."""

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import respx

from conector_odoo.infrastructure.odoo.client import OdooClient
from conector_odoo.infrastructure.odoo.json2 import Json2Transport

URL = "https://odoo.test"
BASE = f"{URL}/json/2"


@pytest.fixture
async def client() -> AsyncIterator[OdooClient]:
    async with httpx.AsyncClient() as http:
        transport = Json2Transport(URL, "db", "bot", "key", client=http, max_retries=0)
        yield OdooClient(transport)


def mock_auth() -> None:
    respx.post(f"{BASE}/res.users/context_get").mock(
        return_value=httpx.Response(200, json={"uid": 42})
    )
    respx.post(f"{BASE}/res.users/search").mock(return_value=httpx.Response(200, json=[42]))


def sent(route: respx.Route) -> Any:
    return json.loads(route.calls[0].request.content)


@respx.mock
async def test_search_read(client: OdooClient) -> None:
    mock_auth()
    route = respx.post(f"{BASE}/res.partner/search_read").mock(
        return_value=httpx.Response(200, json=[{"id": 1}])
    )
    rows = await client.search_read(
        "res.partner", [["name", "ilike", "a"]], ["name"], limit=5, offset=10, order="id asc"
    )
    assert rows == [{"id": 1}]
    assert sent(route) == {
        "domain": [["name", "ilike", "a"]],
        "fields": ["name"],
        "limit": 5,
        "offset": 10,
        "order": "id asc",
    }


@respx.mock
async def test_read(client: OdooClient) -> None:
    mock_auth()
    route = respx.post(f"{BASE}/res.partner/read").mock(
        return_value=httpx.Response(200, json=[{"id": 1, "name": "A"}])
    )
    assert await client.read("res.partner", [1], ["name"]) == [{"id": 1, "name": "A"}]
    assert sent(route) == {"ids": [1], "fields": ["name"]}


@respx.mock
async def test_create_returns_the_first_id_of_the_list_result(client: OdooClient) -> None:
    mock_auth()
    route = respx.post(f"{BASE}/res.partner/create").mock(
        return_value=httpx.Response(200, json=[77])
    )
    assert await client.create("res.partner", {"name": "A"}) == 77
    assert sent(route) == {"vals_list": [{"name": "A"}]}


@respx.mock
async def test_write(client: OdooClient) -> None:
    mock_auth()
    route = respx.post(f"{BASE}/res.partner/write").mock(
        return_value=httpx.Response(200, json=True)
    )
    assert await client.write("res.partner", [3], {"name": "B"}) is True
    assert sent(route) == {"ids": [3], "vals": {"name": "B"}}


@respx.mock
async def test_unlink_archives_through_write(client: OdooClient) -> None:
    mock_auth()
    route = respx.post(f"{BASE}/res.partner/write").mock(
        return_value=httpx.Response(200, json=True)
    )
    assert await client.unlink("res.partner", [3]) is True
    assert sent(route) == {"ids": [3], "vals": {"active": False}}


@respx.mock
async def test_search_count(client: OdooClient) -> None:
    mock_auth()
    route = respx.post(f"{BASE}/res.partner/search_count").mock(
        return_value=httpx.Response(200, json=12)
    )
    assert await client.search_count("res.partner", [["active", "=", True]]) == 12
    assert sent(route) == {"domain": [["active", "=", True]]}


@respx.mock
async def test_execute_kw_action_confirm(client: OdooClient) -> None:
    mock_auth()
    route = respx.post(f"{BASE}/sale.order/action_confirm").mock(
        return_value=httpx.Response(200, json=True)
    )
    assert await client.execute_kw("sale.order", "action_confirm", [[9]]) is True
    assert sent(route) == {"ids": [9]}


@respx.mock
async def test_company_context_travels_in_the_named_context_argument(client: OdooClient) -> None:
    mock_auth()
    route = respx.post(f"{BASE}/sale.order/read").mock(return_value=httpx.Response(200, json=[]))
    await client.read("sale.order", [1], ["name"], company_id=2)
    assert sent(route) == {
        "ids": [1],
        "fields": ["name"],
        "context": {"allowed_company_ids": [2], "company_id": 2},
    }


@respx.mock
async def test_every_call_authenticates_once_and_sends_the_bearer_key(client: OdooClient) -> None:
    mock_auth()
    route = respx.post(f"{BASE}/res.partner/search_count").mock(
        return_value=httpx.Response(200, json=0)
    )
    await client.search_count("res.partner", [])
    await client.search_count("res.partner", [])
    assert route.call_count == 2
    assert route.calls[0].request.headers["authorization"] == "bearer key"
    assert client.uid == 42
