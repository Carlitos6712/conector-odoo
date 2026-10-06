import logging
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
import respx

from conector_odoo.domain.errors import RemoteAuthError, RemoteUnavailable
from conector_odoo.domain.profiles import AuthMethod, Secrets
from tests.rest.helpers import BASE, TOKEN, FakeTime, http_client, profile

TOKEN_URL = "https://idp.test/token"
CLIENT = Secrets(client_id="cid-public", client_secret="csecret-value-9")


def oauth_profile(**kw: Any) -> Any:
    return profile(
        auth_method=AuthMethod.OAUTH2_CLIENT_CREDENTIALS, token_url=TOKEN_URL, scope="read", **kw
    )


def token_response(value: str = "at-1", expires_in: int | None = 3600) -> httpx.Response:
    body: dict[str, Any] = {"access_token": value, "token_type": "Bearer"}
    if expires_in is not None:
        body["expires_in"] = expires_in
    return httpx.Response(200, json=body)


@respx.mock
async def test_api_key_goes_in_the_configured_header() -> None:
    route = respx.get(f"{BASE}/x").respond(200, json={})
    prof = profile(auth_method=AuthMethod.API_KEY, api_key_header="X-Key")
    await http_client(prof, Secrets(api_key="key-123")).request("GET", "/x")
    assert route.calls.last.request.headers["X-Key"] == "key-123"


@respx.mock
async def test_bearer_extra_headers() -> None:
    route = respx.get(f"{BASE}/x").respond(200, json={})
    await http_client(profile(extra_headers={"X-Tenant": "acme"})).request("GET", "/x")
    headers = route.calls.last.request.headers
    assert headers["Authorization"] == f"Bearer {TOKEN}"
    assert headers["X-Tenant"] == "acme"


@pytest.mark.parametrize(
    ("method", "secrets"),
    [
        (AuthMethod.API_KEY, Secrets()),
        (AuthMethod.BEARER, Secrets()),
        (AuthMethod.OAUTH2_CLIENT_CREDENTIALS, Secrets(client_id="only-id")),
    ],
)
async def test_missing_credentials_raise_auth_error(method: AuthMethod, secrets: Secrets) -> None:
    prof = profile(auth_method=method, token_url=TOKEN_URL)
    with pytest.raises(RemoteAuthError, match="required"):
        await http_client(prof, secrets).request("GET", "/x")


@respx.mock
async def test_oauth2_token_is_requested_once_and_cached() -> None:
    token = respx.post(TOKEN_URL).mock(return_value=token_response())
    api = respx.get(f"{BASE}/x").respond(200, json={})
    client = http_client(oauth_profile(), CLIENT)
    await client.request("GET", "/x")
    await client.request("GET", "/x")
    assert token.call_count == 1
    assert api.calls.last.request.headers["Authorization"] == "Bearer at-1"
    form = token.calls[0].request.content.decode()
    assert "grant_type=client_credentials" in form
    assert "scope=read" in form
    assert "client_id=cid-public" in form


@respx.mock
async def test_oauth2_token_is_refreshed_before_expiry_minus_skew() -> None:
    fake = FakeTime()
    token = respx.post(TOKEN_URL).mock(side_effect=[token_response("a", 100), token_response("b")])
    api = respx.get(f"{BASE}/x").respond(200, json={})
    client = http_client(oauth_profile(), CLIENT, fake)
    await client.request("GET", "/x")
    fake.now += 60  # still valid (100s - 30s skew = 70s)
    await client.request("GET", "/x")
    assert token.call_count == 1
    fake.now += 20  # 80s > 70s -> expired
    await client.request("GET", "/x")
    assert token.call_count == 2
    assert api.calls.last.request.headers["Authorization"] == "Bearer b"


@respx.mock
async def test_oauth2_refreshes_once_on_401_then_succeeds() -> None:
    token = respx.post(TOKEN_URL).mock(side_effect=[token_response("old"), token_response("new")])
    api = respx.get(f"{BASE}/x").mock(
        side_effect=lambda r: httpx.Response(
            200 if r.headers["Authorization"] == "Bearer new" else 401, json={}
        )
    )
    await http_client(oauth_profile(), CLIENT).request("GET", "/x")
    assert token.call_count == 2
    assert api.call_count == 2


@respx.mock
async def test_oauth2_persistent_401_refreshes_only_once() -> None:
    token = respx.post(TOKEN_URL).mock(return_value=token_response())
    api = respx.get(f"{BASE}/x").respond(401)
    with pytest.raises(RemoteAuthError):
        await http_client(oauth_profile(), CLIENT).request("GET", "/x")
    assert token.call_count == 2
    assert api.call_count == 2


@respx.mock
async def test_static_credentials_are_not_retried_on_401() -> None:
    api = respx.get(f"{BASE}/x").respond(401)
    with pytest.raises(RemoteAuthError):
        await http_client().request("GET", "/x")
    assert api.call_count == 1


@respx.mock
async def test_token_endpoint_unreachable_is_unavailable() -> None:
    respx.post(TOKEN_URL).mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(RemoteUnavailable, match="token"):
        await http_client(oauth_profile(), CLIENT).request("GET", "/x")


@respx.mock
async def test_token_endpoint_rejection_is_auth_error_without_secrets() -> None:
    respx.post(TOKEN_URL).respond(401, json={"error": "invalid_client"})
    with pytest.raises(RemoteAuthError) as info:
        await http_client(oauth_profile(), CLIENT).request("GET", "/x")
    assert "invalid_client" in str(info.value)
    assert "csecret-value-9" not in str(info.value)


@respx.mock
async def test_oidc_uses_token_url_when_configured() -> None:
    token = respx.post(TOKEN_URL).mock(return_value=token_response())
    respx.get(f"{BASE}/x").respond(200, json={})
    prof = profile(auth_method=AuthMethod.OIDC, token_url=TOKEN_URL)
    await http_client(prof, CLIENT).request("GET", "/x")
    assert token.call_count == 1


@respx.mock
async def test_oidc_discovers_token_endpoint_from_issuer() -> None:
    from conector_odoo.infrastructure.rest.auth import build_authenticator
    from conector_odoo.infrastructure.rest.http import RestHttpClient

    disc = respx.get("https://idp.test/realm/.well-known/openid-configuration").respond(
        200, json={"token_endpoint": TOKEN_URL}
    )
    token = respx.post(TOKEN_URL).mock(return_value=token_response())
    respx.get(f"{BASE}/x").respond(200, json={})
    prof = profile(auth_method=AuthMethod.OIDC)
    auth = build_authenticator(prof, CLIENT, issuer_url="https://idp.test/realm/")
    client = RestHttpClient(BASE, auth)
    await client.request("GET", "/x")
    await client.request("GET", "/x")
    assert disc.call_count == 1
    assert token.call_count == 1


@respx.mock
async def test_oidc_unsupported_grant_type_explains_missing_m2m_flow() -> None:
    respx.post(TOKEN_URL).respond(400, json={"error": "unsupported_grant_type"})
    prof = profile(auth_method=AuthMethod.OIDC, token_url=TOKEN_URL)
    with pytest.raises(RemoteAuthError, match="machine-to-machine"):
        await http_client(prof, CLIENT).request("GET", "/x")


async def test_oidc_without_any_endpoint_info_uses_base_url_discovery() -> None:
    with respx.mock:
        disc = respx.get(f"{BASE}/.well-known/openid-configuration").respond(404)
        prof = profile(auth_method=AuthMethod.OIDC)
        with pytest.raises(RemoteAuthError, match="discover"):
            await http_client(prof, CLIENT).request("GET", "/x")
        assert disc.call_count == 1


@respx.mock
async def test_tls_verify_and_timeout_come_from_the_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[Any, Any]] = []
    real = httpx.AsyncClient

    def spy(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        seen.append((kwargs.get("verify"), kwargs.get("timeout")))
        return real(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", spy)
    respx.get(f"{BASE}/x").respond(200, json={})
    await http_client(profile(tls_verify=False, timeout_seconds=7.0)).request("GET", "/x")
    assert seen == [(False, 7.0)]


@respx.mock
async def test_secrets_never_appear_in_repr_errors_or_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    respx.post(TOKEN_URL).mock(return_value=token_response("at-leaky-token"))
    respx.get(f"{BASE}/x").respond(500, text="boom at-leaky-token csecret-value-9")
    client = http_client(oauth_profile(), CLIENT)
    with pytest.raises(RemoteUnavailable) as info:
        await client.request("GET", "/x")
    everything = repr(client) + repr(client._auth) + str(info.value) + caplog.text
    for secret in ("at-leaky-token", "csecret-value-9"):
        assert secret not in everything
    bearer = http_client()
    assert TOKEN not in repr(bearer) + repr(bearer._auth)


@respx.mock
@pytest.mark.parametrize("status", [429, 500, 502, 503])
async def test_token_endpoint_overload_or_server_error_is_unavailable(status: int) -> None:
    respx.post(TOKEN_URL).respond(status, text="busy")
    with pytest.raises(RemoteUnavailable, match=str(status)):
        await http_client(oauth_profile(), CLIENT).request("GET", "/x")


@respx.mock
@pytest.mark.parametrize("status", [400, 401, 403])
async def test_token_endpoint_client_errors_are_auth_errors(status: int) -> None:
    respx.post(TOKEN_URL).respond(status, json={"error": "invalid_client"})
    with pytest.raises(RemoteAuthError):
        await http_client(oauth_profile(), CLIENT).request("GET", "/x")


USER_PASSWORD = Secrets(client_id="cid-public", password="app-password-77")


@respx.mock
async def test_oauth2_username_password_grant_sends_user_form_without_client_secret() -> None:
    token = respx.post(TOKEN_URL).mock(return_value=token_response())
    respx.get(f"{BASE}/x").respond(200, json={})
    client = http_client(oauth_profile(username="alice"), USER_PASSWORD)
    await client.request("GET", "/x")
    form = parse_qs(token.calls[0].request.content.decode())
    assert form == {
        "grant_type": ["client_credentials"],
        "client_id": ["cid-public"],
        "username": ["alice"],
        "password": ["app-password-77"],
        "scope": ["read"],
    }


@respx.mock
async def test_oauth2_username_password_wins_over_client_secret_when_both_set() -> None:
    token = respx.post(TOKEN_URL).mock(return_value=token_response())
    respx.get(f"{BASE}/x").respond(200, json={})
    secrets = Secrets(client_id="cid", client_secret="csecret-value-9", password="pw-1")
    await http_client(oauth_profile(username="alice"), secrets).request("GET", "/x")
    form = parse_qs(token.calls[0].request.content.decode())
    assert form["username"] == ["alice"]
    assert "client_secret" not in form


@respx.mock
async def test_oauth2_without_username_keeps_client_secret_grant() -> None:
    token = respx.post(TOKEN_URL).mock(return_value=token_response())
    respx.get(f"{BASE}/x").respond(200, json={})
    secrets = Secrets(client_id="cid", client_secret="csecret-value-9", password="pw-1")
    await http_client(oauth_profile(), secrets).request("GET", "/x")
    form = parse_qs(token.calls[0].request.content.decode())
    assert form["client_secret"] == ["csecret-value-9"]
    assert "username" not in form
    assert "password" not in form


@pytest.mark.parametrize(
    ("username", "secrets"),
    [
        ("alice", Secrets(client_id="cid")),
        (None, Secrets(client_id="cid", password="pw")),
        ("alice", Secrets(password="pw")),
    ],
)
async def test_oauth2_incomplete_user_credentials_raise_auth_error(
    username: str | None, secrets: Secrets
) -> None:
    with pytest.raises(RemoteAuthError, match="required"):
        await http_client(oauth_profile(username=username), secrets).request("GET", "/x")


@respx.mock
async def test_oauth2_password_never_appears_in_repr_errors_or_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    respx.post(TOKEN_URL).mock(return_value=token_response("at-ok"))
    respx.get(f"{BASE}/x").respond(500, text="boom app-password-77")
    client = http_client(oauth_profile(username="alice"), USER_PASSWORD)
    with pytest.raises(RemoteUnavailable) as info:
        await client.request("GET", "/x")
    everything = repr(client) + repr(client._auth) + str(info.value) + caplog.text
    assert "app-password-77" not in everything
    assert "app-password-77" in client._auth.secret_values()
