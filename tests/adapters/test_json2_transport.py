import json
from typing import Any

import httpx
import pytest
import respx

from conector_odoo.domain.errors import (
    OdooAuthError,
    OdooNotFound,
    OdooPermissionError,
    OdooUnavailable,
    OdooValidationError,
)
from conector_odoo.infrastructure.odoo.json2 import Json2Transport

URL = "https://odoo.test"
KEY = "key-123"


def err(status: int, name: str, message: str = "nope", debug: str = "") -> httpx.Response:
    return httpx.Response(
        status,
        json={"name": name, "message": message, "arguments": [message], "debug": debug},
    )


class Harness:
    def __init__(self, transport: Json2Transport, sleeps: list[float]) -> None:
        self.transport = transport
        self.sleeps = sleeps


@pytest.fixture
async def harness() -> Any:
    sleeps: list[float] = []

    async def sleep(delay: float) -> None:
        sleeps.append(delay)

    async with httpx.AsyncClient() as client:
        transport = Json2Transport(
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


def body(call: respx.models.Call) -> Any:
    return json.loads(call.request.content)


def mock_identity(uid: object = 42, users: object = None) -> tuple[respx.Route, respx.Route]:
    """Mock ``res.users/context_get`` (key owner) and ``res.users/search`` (login lookup)."""
    context = respx.post(f"{URL}/json/2/res.users/context_get").mock(
        return_value=httpx.Response(200, json={"lang": "en_US", "tz": "UTC", "uid": uid})
    )
    search = respx.post(f"{URL}/json/2/res.users/search").mock(
        return_value=httpx.Response(200, json=[42] if users is None else users)
    )
    return context, search


@respx.mock
async def test_authenticate_returns_the_user_id_when_key_owner_matches_the_login(
    harness: Harness,
) -> None:
    context, search = mock_identity(uid=42)
    assert await harness.transport.authenticate() == 42
    request = context.calls[0].request
    assert request.headers["authorization"] == f"bearer {KEY}"
    assert request.headers["x-odoo-database"] == "db"
    assert request.headers["content-type"] == "application/json; charset=utf-8"
    assert body(search.calls[0]) == {"domain": [["login", "=", "bot"]], "limit": 1}


@respx.mock
async def test_authenticate_rejects_a_key_that_belongs_to_another_user(harness: Harness) -> None:
    mock_identity(uid=7, users=[42])
    with pytest.raises(OdooAuthError) as info:
        await harness.transport.authenticate()
    assert KEY not in str(info.value)


@respx.mock
async def test_authenticate_without_matching_login_is_auth_error(harness: Harness) -> None:
    mock_identity(uid=42, users=[])
    with pytest.raises(OdooAuthError) as info:
        await harness.transport.authenticate()
    assert KEY not in str(info.value)


@respx.mock
async def test_authenticate_with_rejected_key_is_auth_error(harness: Harness) -> None:
    respx.post(f"{URL}/json/2/res.users/context_get").mock(return_value=httpx.Response(401))
    respx.post(f"{URL}/json/2/res.users/search").mock(return_value=httpx.Response(401))
    with pytest.raises(OdooAuthError):
        await harness.transport.authenticate()


@pytest.mark.parametrize("context", [{"lang": "en_US"}, [], "x", {"uid": "7"}, {"uid": True}])
@respx.mock
async def test_authenticate_without_a_usable_uid_in_context_falls_back_to_the_login_lookup(
    harness: Harness, context: object, caplog: pytest.LogCaptureFixture
) -> None:
    respx.post(f"{URL}/json/2/res.users/context_get").mock(
        return_value=httpx.Response(200, json=context)
    )
    respx.post(f"{URL}/json/2/res.users/search").mock(return_value=httpx.Response(200, json=[42]))
    with caplog.at_level("WARNING"):
        assert await harness.transport.authenticate() == 42
    assert "could not verify" in caplog.text
    assert "context_get returned no usable uid" in caplog.text


@pytest.mark.parametrize("status", [403, 404, 500])
@respx.mock
async def test_authenticate_falls_back_to_the_login_lookup_when_context_get_fails(
    harness: Harness, status: int, caplog: pytest.LogCaptureFixture
) -> None:
    respx.post(f"{URL}/json/2/res.users/context_get").mock(return_value=httpx.Response(status))
    search = respx.post(f"{URL}/json/2/res.users/search").mock(
        return_value=httpx.Response(200, json=[42])
    )
    with caplog.at_level("WARNING"):
        assert await harness.transport.authenticate() == 42
    assert search.called
    assert "context_get failed" in caplog.text


@pytest.mark.parametrize(
    ("method", "args", "kwargs", "expected"),
    [
        (
            "search_read",
            [[["name", "=", "A"]]],
            {"fields": ["name"], "limit": 5, "offset": 10, "order": "id asc"},
            {
                "domain": [["name", "=", "A"]],
                "fields": ["name"],
                "limit": 5,
                "offset": 10,
                "order": "id asc",
            },
        ),
        ("search", [[["a", "=", 1]]], {"limit": 2}, {"domain": [["a", "=", 1]], "limit": 2}),
        ("search_count", [[]], {}, {"domain": []}),
        ("read", [[1, 2]], {"fields": ["name"]}, {"ids": [1, 2], "fields": ["name"]}),
        ("create", [{"name": "A"}], {}, {"vals_list": [{"name": "A"}]}),
        (
            "create",
            [[{"name": "A"}, {"name": "B"}]],
            {},
            {"vals_list": [{"name": "A"}, {"name": "B"}]},
        ),
        ("write", [[3], {"name": "B"}], {}, {"ids": [3], "vals": {"name": "B"}}),
        ("action_confirm", [[9]], {}, {"ids": [9]}),
    ],
)
@respx.mock
async def test_positional_arguments_become_named_arguments(
    harness: Harness, method: str, args: list[Any], kwargs: dict[str, Any], expected: dict[str, Any]
) -> None:
    route = respx.post(f"{URL}/json/2/res.partner/{method}").mock(
        return_value=httpx.Response(200, json=[1])
    )
    result = await harness.transport.execute_kw("res.partner", method, args, kwargs)
    assert result == [1]
    assert body(route.calls[0]) == expected
    assert route.calls[0].request.headers["authorization"] == f"bearer {KEY}"


@respx.mock
async def test_context_kwarg_is_sent_as_context_key(harness: Harness) -> None:
    route = respx.post(f"{URL}/json/2/sale.order/read").mock(
        return_value=httpx.Response(200, json=[])
    )
    context = {"allowed_company_ids": [2], "company_id": 2}
    await harness.transport.execute_kw("sale.order", "read", [[1]], {"context": context})
    assert body(route.calls[0]) == {"ids": [1], "context": context}


async def test_unsupported_method_is_rejected_without_a_request(harness: Harness) -> None:
    with respx.mock:
        with pytest.raises(OdooUnavailable) as info:
            await harness.transport.execute_kw("res.partner", "mystery", [[1]])
        assert "mystery" in str(info.value)


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (err(404, "odoo.exceptions.MissingError"), OdooNotFound),
        (err(403, "odoo.exceptions.AccessError"), OdooPermissionError),
        (httpx.Response(403), OdooPermissionError),
        (err(401, "odoo.exceptions.AccessDenied"), OdooAuthError),
        (httpx.Response(401), OdooAuthError),
        (err(422, "odoo.exceptions.ValidationError"), OdooValidationError),
        (err(422, "odoo.exceptions.UserError"), OdooValidationError),
        (err(400, "odoo.exceptions.UserError"), OdooValidationError),
        (httpx.Response(404, text="not found"), OdooUnavailable),
        (err(500, "builtins.ZeroDivisionError"), OdooUnavailable),
        (httpx.Response(502), OdooUnavailable),
    ],
)
@respx.mock
async def test_http_errors_are_mapped(
    harness: Harness, response: httpx.Response, expected: type[Exception]
) -> None:
    respx.post(f"{URL}/json/2/res.partner/read").mock(return_value=response)
    with pytest.raises(expected) as info:
        await harness.transport.execute_kw("res.partner", "read", [[1]])
    assert type(info.value) is expected
    assert KEY not in str(info.value)


@respx.mock
async def test_error_messages_hide_secrets_and_debug(harness: Harness) -> None:
    respx.post(f"{URL}/json/2/res.partner/read").mock(
        return_value=err(
            422, "odoo.exceptions.UserError", f"bad {KEY} value", debug=f"Traceback {KEY}"
        )
    )
    with pytest.raises(OdooValidationError) as info:
        await harness.transport.execute_kw("res.partner", "read", [[1]])
    assert KEY not in str(info.value)
    assert "Traceback" not in str(info.value)


@respx.mock
async def test_network_errors_are_retried_on_idempotent_calls(harness: Harness) -> None:
    route = respx.post(f"{URL}/json/2/res.partner/search").mock(
        side_effect=[httpx.ConnectError("x"), httpx.ReadTimeout("t"), httpx.Response(200, json=[1])]
    )
    assert await harness.transport.execute_kw("res.partner", "search", [[]]) == [1]
    assert route.call_count == 3
    assert harness.sleeps == [0.5, 1.0]


@respx.mock
async def test_retries_are_bounded_then_unavailable(harness: Harness) -> None:
    route = respx.post(f"{URL}/json/2/res.partner/search_read").mock(
        side_effect=httpx.ConnectError("x")
    )
    with pytest.raises(OdooUnavailable):
        await harness.transport.execute_kw("res.partner", "search_read", [[]])
    assert route.call_count == 3


@pytest.mark.parametrize("method", ["create", "write", "action_confirm"])
@respx.mock
async def test_non_idempotent_calls_are_never_retried(harness: Harness, method: str) -> None:
    route = respx.post(f"{URL}/json/2/res.partner/{method}").mock(
        side_effect=httpx.ConnectError("x")
    )
    args: list[Any] = {"create": [{"name": "A"}], "write": [[1], {}], "action_confirm": [[1]]}[
        method
    ]
    with pytest.raises(OdooUnavailable) as info:
        await harness.transport.execute_kw("res.partner", method, args)
    assert "not retried" in str(info.value)
    assert route.call_count == 1
    assert harness.sleeps == []


@respx.mock
async def test_5xx_is_not_retried(harness: Harness) -> None:
    route = respx.post(f"{URL}/json/2/res.partner/search").mock(return_value=httpx.Response(502))
    with pytest.raises(OdooUnavailable):
        await harness.transport.execute_kw("res.partner", "search", [[]])
    assert route.call_count == 1


@respx.mock
async def test_non_json_success_body_is_unavailable(harness: Harness) -> None:
    respx.post(f"{URL}/json/2/res.partner/search").mock(
        return_value=httpx.Response(200, text="<html>")
    )
    with pytest.raises(OdooUnavailable):
        await harness.transport.execute_kw("res.partner", "search", [[]])


async def test_aclose_closes_owned_client_only() -> None:
    owned = Json2Transport(url=URL, db="d", user="u", api_key=KEY)
    inner = owned._client
    await owned.aclose()
    assert inner.is_closed
    async with httpx.AsyncClient() as client:
        shared = Json2Transport(url=URL, db="d", user="u", api_key=KEY, client=client)
        await shared.aclose()
        assert not client.is_closed
