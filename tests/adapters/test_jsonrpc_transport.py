import json
from typing import Any

import httpx
import pytest
import respx

from conector_odoo.domain.errors import (
    OdooAuthError,
    OdooNotFound,
    OdooUnavailable,
    OdooValidationError,
)
from conector_odoo.infrastructure.odoo.jsonrpc import JsonRpcTransport

URL = "https://odoo.test"
KEY = "key-123"


def ok(result: Any) -> httpx.Response:
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})


def fail(name: str, message: str = "nope", debug: str = "") -> httpx.Response:
    error = {
        "code": 200,
        "message": "Odoo Server Error",
        "data": {"name": name, "message": message, "debug": debug},
    }
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "error": error})


class Harness:
    def __init__(self, transport: JsonRpcTransport, sleeps: list[float]) -> None:
        self.transport = transport
        self.sleeps = sleeps


@pytest.fixture
async def harness() -> Any:
    sleeps: list[float] = []

    async def sleep(delay: float) -> None:
        sleeps.append(delay)

    async with httpx.AsyncClient() as client:
        transport = JsonRpcTransport(
            url=URL,
            db="db",
            user="bot",
            api_key=KEY,
            timeout=3.0,
            max_retries=2,
            client=client,
            sleep=sleep,
            backoff_base=0.5,
        )
        yield Harness(transport, sleeps)


def body(call: respx.models.Call) -> dict[str, Any]:
    return json.loads(call.request.content)  # type: ignore[no-any-return]


@respx.mock
async def test_authenticate_posts_common_service(harness: Harness) -> None:
    route = respx.post(f"{URL}/jsonrpc").mock(return_value=ok(7))
    assert await harness.transport.authenticate() == 7
    payload = body(route.calls[0])
    assert payload["method"] == "call"
    assert payload["params"] == {
        "service": "common",
        "method": "authenticate",
        "args": ["db", "bot", KEY, {}],
    }


@pytest.mark.parametrize("falsy", [False, 0, None])
@respx.mock
async def test_authenticate_falsy_uid_is_auth_error(harness: Harness, falsy: Any) -> None:
    respx.post(f"{URL}/jsonrpc").mock(return_value=ok(falsy))
    with pytest.raises(OdooAuthError) as info:
        await harness.transport.authenticate()
    assert KEY not in str(info.value)


@respx.mock
async def test_execute_kw_payload_and_lazy_authentication(harness: Harness) -> None:
    route = respx.post(f"{URL}/jsonrpc").mock(side_effect=[ok(7), ok([{"id": 1}])])
    result = await harness.transport.execute_kw(
        "res.partner", "search_read", [[["name", "=", "A"]]], {"limit": 1}
    )
    assert result == [{"id": 1}]
    assert route.call_count == 2
    assert body(route.calls[1])["params"] == {
        "service": "object",
        "method": "execute_kw",
        "args": ["db", 7, KEY, "res.partner", "search_read", [[["name", "=", "A"]]], {"limit": 1}],
    }


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("odoo.exceptions.AccessDenied", OdooAuthError),
        ("odoo.exceptions.MissingError", OdooNotFound),
        ("odoo.exceptions.ValidationError", OdooValidationError),
        ("odoo.exceptions.UserError", OdooValidationError),
        ("builtins.ZeroDivisionError", OdooUnavailable),
    ],
)
@respx.mock
async def test_odoo_errors_are_mapped(
    harness: Harness, name: str, expected: type[Exception]
) -> None:
    respx.post(f"{URL}/jsonrpc").mock(side_effect=[ok(7), fail(name, debug=f"trace {KEY}")])
    with pytest.raises(expected) as info:
        await harness.transport.execute_kw("res.partner", "read", [[1]])
    assert KEY not in str(info.value)
    assert "trace" not in str(info.value)


@respx.mock
async def test_network_errors_are_retried_on_idempotent_calls(harness: Harness) -> None:
    route = respx.post(f"{URL}/jsonrpc").mock(
        side_effect=[ok(7), httpx.ConnectError("x"), httpx.ReadTimeout("t"), ok([1])]
    )
    result = await harness.transport.execute_kw("res.partner", "search", [[]])
    assert result == [1]
    assert route.call_count == 4
    assert harness.sleeps == [0.5, 1.0]


@respx.mock
async def test_retries_are_bounded_then_unavailable(harness: Harness) -> None:
    route = respx.post(f"{URL}/jsonrpc").mock(
        side_effect=[
            ok(7),
            httpx.ConnectError("x"),
            httpx.ConnectError("x"),
            httpx.ConnectError("x"),
        ]
    )
    with pytest.raises(OdooUnavailable):
        await harness.transport.execute_kw("res.partner", "search_read", [[]])
    assert route.call_count == 4  # 1 auth + 1 attempt + 2 retries


@pytest.mark.parametrize("method", ["create", "write", "unlink", "action_confirm", "mystery"])
@respx.mock
async def test_non_idempotent_calls_are_never_retried(harness: Harness, method: str) -> None:
    route = respx.post(f"{URL}/jsonrpc").mock(side_effect=[ok(7), httpx.ConnectError("x")])
    with pytest.raises(OdooUnavailable):
        await harness.transport.execute_kw("res.partner", method, [[{"name": "A"}]])
    assert route.call_count == 2  # auth + a single attempt
    assert harness.sleeps == []


@respx.mock
async def test_timeout_maps_to_unavailable(harness: Harness) -> None:
    respx.post(f"{URL}/jsonrpc").mock(side_effect=[ok(7), httpx.ReadTimeout("slow")])
    with pytest.raises(OdooUnavailable):
        await harness.transport.execute_kw("res.partner", "create", [[{"name": "A"}]])


@respx.mock
async def test_http_5xx_is_unavailable_and_not_retried(harness: Harness) -> None:
    route = respx.post(f"{URL}/jsonrpc").mock(side_effect=[ok(7), httpx.Response(502)])
    with pytest.raises(OdooUnavailable):
        await harness.transport.execute_kw("res.partner", "search", [[]])
    assert route.call_count == 2


@respx.mock
async def test_http_401_is_auth_error(harness: Harness) -> None:
    respx.post(f"{URL}/jsonrpc").mock(return_value=httpx.Response(401))
    with pytest.raises(OdooAuthError):
        await harness.transport.authenticate()


@respx.mock
async def test_non_json_body_is_unavailable(harness: Harness) -> None:
    respx.post(f"{URL}/jsonrpc").mock(return_value=httpx.Response(200, text="<html>"))
    with pytest.raises(OdooUnavailable):
        await harness.transport.authenticate()


@respx.mock
async def test_aclose_keeps_injected_client_open() -> None:
    async with httpx.AsyncClient() as client:
        transport = JsonRpcTransport(url=URL, db="d", user="u", api_key=KEY, client=client)
        await transport.aclose()
        assert not client.is_closed


async def test_aclose_closes_owned_client() -> None:
    transport = JsonRpcTransport(url=URL, db="d", user="u", api_key=KEY)
    await transport.aclose()
