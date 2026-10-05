import httpx
import pytest
import respx

from conector_odoo.domain.errors import (
    RecordRejected,
    RemoteAuthError,
    RemoteUnavailable,
    ResourceNotFound,
)
from tests.rest.helpers import BASE, TOKEN, FakeTime, http_client

URL = f"{BASE}/x"


@respx.mock
async def test_transport_errors_are_retried_with_exponential_backoff() -> None:
    fake = FakeTime()
    route = respx.get(URL).mock(
        side_effect=[httpx.ConnectError("x"), httpx.ReadTimeout("y"), httpx.Response(200, json={})]
    )
    response = await http_client(fake=fake, max_retries=3, backoff_base=0.5).request("GET", "/x")
    assert response.status_code == 200
    assert route.call_count == 3
    assert fake.sleeps == [0.5, 1.0]


@respx.mock
async def test_retries_exhausted_raise_unavailable() -> None:
    route = respx.get(URL).mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(RemoteUnavailable, match="ConnectError"):
        await http_client(max_retries=2).request("GET", "/x")
    assert route.call_count == 3


@respx.mock
@pytest.mark.parametrize("status", [429, 500, 502, 503])
async def test_http_status_errors_are_never_retried(status: int) -> None:
    route = respx.get(URL).respond(status, text="nope")
    with pytest.raises(RemoteUnavailable, match=str(status)):
        await http_client(max_retries=3).request("GET", "/x")
    assert route.call_count == 1


@respx.mock
async def test_post_without_idempotency_key_is_never_retried() -> None:
    route = respx.post(URL).mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(RemoteUnavailable):
        await http_client(max_retries=3).request("POST", "/x", json={"a": 1})
    assert route.call_count == 1


@respx.mock
async def test_post_with_idempotency_key_is_retried_with_the_same_key() -> None:
    route = respx.post(URL).mock(
        side_effect=[httpx.ReadTimeout("slow"), httpx.Response(201, json={"id": 1})]
    )
    await http_client(max_retries=3).request("POST", "/x", json={}, idempotency_key="k-1")
    assert route.call_count == 2
    assert [c.request.headers["Idempotency-Key"] for c in route.calls] == ["k-1", "k-1"]


@respx.mock
async def test_idempotency_header_name_is_configurable() -> None:
    route = respx.post(URL).respond(201, json={})
    client = http_client(idempotency_header="X-Request-Id")
    await client.request("POST", "/x", json={}, idempotency_key="k-2")
    assert route.calls.last.request.headers["X-Request-Id"] == "k-2"
    assert "Idempotency-Key" not in route.calls.last.request.headers


@respx.mock
async def test_rate_limiter_spaces_requests_with_the_fake_clock() -> None:
    fake = FakeTime()
    respx.get(URL).respond(200, json={})
    client = http_client(fake=fake, min_interval=1.0)
    for _ in range(3):
        await client.request("GET", "/x")
    assert fake.sleeps == [1.0, 1.0]


@respx.mock
async def test_rate_limiter_does_not_sleep_when_enough_time_passed() -> None:
    fake = FakeTime()
    respx.get(URL).respond(200, json={})
    client = http_client(fake=fake, min_interval=1.0)
    await client.request("GET", "/x")
    fake.now += 5
    await client.request("GET", "/x")
    assert fake.sleeps == []


@respx.mock
@pytest.mark.parametrize(
    ("status", "error"),
    [
        (401, RemoteAuthError),
        (403, RemoteAuthError),
        (404, ResourceNotFound),
        (400, RecordRejected),
        (409, RecordRejected),
        (422, RecordRejected),
        (429, RemoteUnavailable),
        (500, RemoteUnavailable),
        (503, RemoteUnavailable),
        (405, RemoteUnavailable),
    ],
)
async def test_status_codes_map_to_domain_errors(status: int, error: type[Exception]) -> None:
    respx.get(URL).respond(status, text="problem")
    with pytest.raises(error):
        await http_client().request("GET", "/x")


@respx.mock
@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"detail": [{"loc": ["body", "email"], "msg": "not valid"}]}, {"email": "not valid"}),
        (
            {"errors": {"email": ["bad", "worse"], "name": "required"}},
            {"email": "bad; worse", "name": "required"},
        ),
        ({"errors": [{"field": "phone", "message": "too short"}]}, {"phone": "too short"}),
        ({"message": "Duplicate customer"}, {}),
    ],
)
async def test_rejection_field_errors_are_parsed(body: dict, expected: dict) -> None:  # type: ignore[type-arg]
    respx.post(URL).respond(422, json=body)
    with pytest.raises(RecordRejected) as info:
        await http_client().request("POST", "/x", json={})
    assert info.value.field_errors == expected
    if "message" in body:
        assert "Duplicate customer" in str(info.value)


@respx.mock
async def test_error_snippet_is_truncated_and_redacts_the_token() -> None:
    respx.get(URL).respond(500, text=f"{TOKEN} " + "a" * 5000)
    with pytest.raises(RemoteUnavailable) as info:
        await http_client().request("GET", "/x")
    message = str(info.value)
    assert TOKEN not in message
    assert "HTTP 500" in message
    assert len(message) < 500


@respx.mock
async def test_invalid_url_is_a_domain_error_not_a_raw_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def bad_url(*args: object, **kwargs: object) -> httpx.Response:
        raise httpx.InvalidURL("bad url with secret?")

    monkeypatch.setattr(httpx.AsyncClient, "request", bad_url)
    with pytest.raises(RemoteUnavailable, match="invalid request") as info:
        await http_client().request("GET", "/x")
    assert "secret" not in str(info.value)


@respx.mock
async def test_unicode_error_is_a_domain_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def bad_encoding(*args: object, **kwargs: object) -> httpx.Response:
        raise UnicodeEncodeError("ascii", "€", 0, 1, "cannot encode")

    monkeypatch.setattr(httpx.AsyncClient, "request", bad_encoding)
    with pytest.raises(RemoteUnavailable, match="invalid request"):
        await http_client().request("GET", "/x")


async def test_unsupported_protocol_fails_fast_without_retries() -> None:
    fake = FakeTime()
    client = http_client(fake=fake, max_retries=3)
    client._base_url = "ftp://api.test"
    with pytest.raises(RemoteUnavailable, match="invalid request"):
        await client.request("GET", "/x")
    assert fake.sleeps == []
