import asyncio
import json
from typing import Any

import httpx
import pytest
import respx

from conector_odoo.domain.errors import OdooAuthError, OdooPermissionError, OdooUnavailable
from conector_odoo.infrastructure.odoo.client import OdooClient
from conector_odoo.infrastructure.odoo.jsonrpc import JsonRpcTransport

Call = tuple[str, str, list[Any], dict[str, Any]]


class FakeTransport:
    def __init__(self) -> None:
        self.auth_calls = 0
        self.calls: list[Call] = []
        self.results: list[Any] = []

    async def authenticate(self) -> int:
        self.auth_calls += 1
        await asyncio.sleep(0)
        return 10 + self.auth_calls

    async def execute_kw(
        self, model: str, method: str, args: list[Any], kwargs: dict[str, Any] | None = None
    ) -> Any:
        self.calls.append((model, method, args, dict(kwargs or {})))
        await asyncio.sleep(0)
        if self.results:
            item = self.results.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item
        return {"search_count": 0, "search_read": [], "read": []}.get(method)

    async def aclose(self) -> None:
        return None


async def test_authenticates_once_under_concurrency() -> None:
    transport = FakeTransport()
    client = OdooClient(transport)
    await asyncio.gather(*(client.search_count("res.partner", []) for _ in range(10)))
    assert transport.auth_calls == 1
    assert client.uid == 11


async def test_reauthenticates_once_and_retries_on_auth_error() -> None:
    transport = FakeTransport()
    transport.results = [OdooAuthError("expired"), [1, 2]]
    client = OdooClient(transport)
    assert await client.execute_kw("res.partner", "search", [[]]) == [1, 2]
    assert transport.auth_calls == 2
    assert len(transport.calls) == 2


async def test_second_auth_error_propagates() -> None:
    transport = FakeTransport()
    transport.results = [OdooAuthError("a"), OdooAuthError("b")]
    client = OdooClient(transport)
    with pytest.raises(OdooAuthError):
        await client.execute_kw("res.partner", "create", [[{"name": "A"}]])
    assert len(transport.calls) == 2
    assert transport.auth_calls == 2


async def test_concurrent_auth_failures_trigger_a_single_reauth() -> None:
    transport = FakeTransport()
    transport.results = [OdooAuthError("x"), OdooAuthError("x"), 1, 2]
    client = OdooClient(transport)
    await asyncio.gather(
        client.execute_kw("res.partner", "search_count", [[]]),
        client.execute_kw("res.partner", "search_count", [[]]),
    )
    assert transport.auth_calls == 2


async def test_other_errors_are_not_retried() -> None:
    transport = FakeTransport()
    transport.results = [OdooUnavailable("down")]
    client = OdooClient(transport)
    with pytest.raises(OdooUnavailable):
        await client.execute_kw("res.partner", "search", [[]])
    assert len(transport.calls) == 1
    assert transport.auth_calls == 1


async def test_permission_error_is_not_replayed() -> None:
    transport = FakeTransport()
    transport.results = [OdooPermissionError("not allowed"), 99]
    client = OdooClient(transport)
    with pytest.raises(OdooPermissionError):
        await client.execute_kw("res.partner", "create", [[{"name": "A"}]])
    assert len(transport.calls) == 1
    assert transport.auth_calls == 1


@pytest.mark.parametrize(
    "denied",
    [
        httpx.Response(403),
        httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "error": {
                    "code": 200,
                    "message": "Odoo Server Error",
                    "data": {"name": "odoo.exceptions.AccessError", "message": "nope"},
                },
            },
        ),
    ],
)
@respx.mock
async def test_access_error_and_403_do_not_reauthenticate_over_jsonrpc(
    denied: httpx.Response,
) -> None:
    ok = httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": 7})
    route = respx.post("https://odoo.test/jsonrpc").mock(side_effect=[ok, denied, ok, ok])
    transport = JsonRpcTransport(url="https://odoo.test", db="d", user="u", api_key="k")
    client = OdooClient(transport)
    with pytest.raises(OdooPermissionError):
        await client.create("res.partner", {"name": "A"})
    assert route.call_count == 2  # one authenticate + one object call, no replay
    await client.aclose()


@pytest.mark.parametrize("bad", [[], None, False, "x"])
async def test_create_with_unexpected_result_is_unavailable(bad: Any) -> None:
    transport = FakeTransport()
    transport.results = [bad]
    with pytest.raises(OdooUnavailable):
        await OdooClient(transport).create("res.partner", {"name": "A"})


async def test_failed_reauth_resets_cached_uid() -> None:
    class Flaky(FakeTransport):
        async def authenticate(self) -> int:
            self.auth_calls += 1
            if self.auth_calls == 2:
                raise OdooAuthError("revoked")
            return 5

    transport = Flaky()
    transport.results = [OdooAuthError("expired")]
    client = OdooClient(transport)
    with pytest.raises(OdooAuthError):
        await client.search_count("res.partner", [])
    assert client.uid is None
    await client.search_count("res.partner", [])
    assert client.uid == 5


async def test_search_read_builds_kwargs() -> None:
    transport = FakeTransport()
    transport.results = [[{"id": 1}]]
    client = OdooClient(transport)
    result = await client.search_read(
        "res.partner", [["name", "ilike", "a"]], ["name"], limit=5, offset=10, order="name asc"
    )
    assert result == [{"id": 1}]
    assert transport.calls[0] == (
        "res.partner",
        "search_read",
        [[["name", "ilike", "a"]]],
        {"fields": ["name"], "limit": 5, "offset": 10, "order": "name asc"},
    )


async def test_read_create_write_count() -> None:
    transport = FakeTransport()
    transport.results = [[{"id": 3}], 42, True, 9]
    client = OdooClient(transport)
    assert await client.read("res.partner", [3], ["name"]) == [{"id": 3}]
    assert await client.create("res.partner", {"name": "A"}) == 42
    assert await client.write("res.partner", [42], {"name": "B"}) is True
    assert await client.search_count("res.partner", [["active", "=", True]]) == 9
    assert [c[1] for c in transport.calls] == ["read", "create", "write", "search_count"]
    assert transport.calls[0][2] == [[3]]
    assert transport.calls[0][3] == {"fields": ["name"]}
    assert transport.calls[1][2] == [{"name": "A"}]
    assert transport.calls[2][2] == [[42], {"name": "B"}]


async def test_unlink_is_a_soft_delete() -> None:
    transport = FakeTransport()
    transport.results = [True]
    client = OdooClient(transport)
    assert await client.unlink("res.partner", [4]) is True
    model, method, args, _ = transport.calls[0]
    assert (model, method) == ("res.partner", "write")
    assert args == [[4], {"active": False}]


async def test_company_context_defaults_and_overrides() -> None:
    transport = FakeTransport()
    client = OdooClient(transport, company_id=2)
    await client.search_count("res.partner", [])
    await client.search_count("res.partner", [], company_id=5)
    assert transport.calls[0][3]["context"] == {"allowed_company_ids": [2], "company_id": 2}
    assert transport.calls[1][3]["context"] == {"allowed_company_ids": [5], "company_id": 5}


async def test_company_context_merges_with_provided_context() -> None:
    transport = FakeTransport()
    client = OdooClient(transport, company_id=2)
    await client.search_read("res.partner", [], context={"lang": "es_ES"})
    assert transport.calls[0][3]["context"] == {
        "allowed_company_ids": [2],
        "company_id": 2,
        "lang": "es_ES",
    }


async def test_no_context_without_company() -> None:
    transport = FakeTransport()
    await OdooClient(transport).search_count("res.partner", [])
    assert "context" not in transport.calls[0][3]


async def test_check_reports_uid() -> None:
    transport = FakeTransport()
    assert await OdooClient(transport).check() == {"status": "ok", "uid": 11}


async def test_aclose_delegates() -> None:
    closed: list[bool] = []

    class T(FakeTransport):
        async def aclose(self) -> None:
            closed.append(True)

    await OdooClient(T()).aclose()
    assert closed == [True]


@respx.mock
async def test_end_to_end_reauth_over_jsonrpc() -> None:
    def rpc(result: Any) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    denied = httpx.Response(
        200,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "error": {
                "code": 100,
                "message": "Odoo Session Expired",
                "data": {"name": "odoo.exceptions.AccessDenied", "message": "Access Denied"},
            },
        },
    )
    route = respx.post("https://odoo.test/jsonrpc").mock(
        side_effect=[rpc(7), denied, rpc(8), rpc(55)]
    )
    transport = JsonRpcTransport(url="https://odoo.test", db="d", user="u", api_key="k")
    client = OdooClient(transport, company_id=1)
    assert await client.create("res.partner", {"name": "A"}) == 55
    services = [json.loads(c.request.content)["params"]["service"] for c in route.calls]
    assert services == ["common", "object", "common", "object"]
    last = json.loads(route.calls[3].request.content)["params"]["args"]
    assert last[1] == 8
    assert last[-1]["context"] == {"allowed_company_ids": [1], "company_id": 1}
    await client.aclose()
