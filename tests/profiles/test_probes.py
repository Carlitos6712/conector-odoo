from typing import Any

import httpx
import pytest
import respx

from conector_odoo.domain.errors import OdooAuthError, OdooUnavailable
from conector_odoo.domain.profiles import (
    AuthMethod,
    ConnectionProfile,
    ProbeStep,
    ProfileType,
    Secrets,
)
from conector_odoo.infrastructure.profiles.odoo_probe import OdooConnectionProbe
from conector_odoo.infrastructure.profiles.rest_probe import RestConnectionProbe

BASE = "https://api.test"
SECRET = "probe-secret-value-1"


def rest(**overrides: Any) -> ConnectionProfile:
    values: dict[str, Any] = {
        "id": None,
        "name": "p",
        "type": ProfileType.REST,
        "base_url": BASE,
        "auth_method": AuthMethod.API_KEY,
        "timeout_seconds": 2.0,
    }
    values.update(overrides)
    return ConnectionProfile(**values)


def names(steps: list[ProbeStep]) -> list[tuple[str, bool]]:
    return [(s.name, s.ok) for s in steps]


def failing(steps: list[ProbeStep]) -> ProbeStep:
    assert not steps[-1].ok
    assert all(s.ok for s in steps[:-1])
    return steps[-1]


@pytest.mark.parametrize("url", ["", "api.test", "ftp://api.test", "https://", "http:///x"])
async def test_invalid_url_stops_at_url_valid(url: str) -> None:
    steps = await RestConnectionProbe().probe(rest(base_url=url), Secrets(api_key=SECRET))
    assert names(steps) == [("url_valid", False)]
    assert steps[0].hint


@respx.mock
async def test_all_steps_pass_with_api_key_header() -> None:
    root = respx.get(BASE)
    root.side_effect = lambda request: httpx.Response(
        200 if request.headers.get("X-API-Key") == SECRET else 401
    )
    steps = await RestConnectionProbe().probe(rest(), Secrets(api_key=SECRET))
    assert names(steps) == [
        ("url_valid", True),
        ("reachable", True),
        ("tls", True),
        ("auth", True),
    ]
    assert SECRET not in repr(steps)


@respx.mock
async def test_extra_headers_and_custom_api_key_header_are_sent() -> None:
    route = respx.get(BASE).respond(200)
    profile = rest(extra_headers={"X-Tenant": "acme"}, api_key_header="X-Key")
    await RestConnectionProbe().probe(profile, Secrets(api_key=SECRET))
    last = route.calls.last.request
    assert last.headers["X-Tenant"] == "acme"
    assert last.headers["X-Key"] == SECRET


@respx.mock
async def test_dns_failure_fails_reachable() -> None:
    respx.get(BASE).mock(side_effect=httpx.ConnectError("[Errno -2] Name or service not known"))
    steps = await RestConnectionProbe().probe(rest(), Secrets())
    step = failing(steps)
    assert step.name == "reachable"
    assert "DNS" in step.detail
    assert step.hint


@respx.mock
async def test_connection_refused_fails_reachable() -> None:
    respx.get(BASE).mock(side_effect=httpx.ConnectError("refused"))
    step = failing(await RestConnectionProbe().probe(rest(), Secrets()))
    assert step.name == "reachable"
    assert "refused" in step.detail.lower() or "connect" in step.detail.lower()


@respx.mock
async def test_timeout_fails_reachable() -> None:
    respx.get(BASE).mock(side_effect=httpx.ConnectTimeout("slow"))
    step = failing(await RestConnectionProbe().probe(rest(), Secrets()))
    assert step.name == "reachable"
    assert "timed out" in step.detail
    assert "timeout" in (step.hint or "").lower()


@respx.mock
async def test_tls_error_fails_tls_after_reachable() -> None:
    err = httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")
    respx.get(BASE).mock(side_effect=err)
    steps = await RestConnectionProbe().probe(rest(), Secrets())
    assert names(steps) == [("url_valid", True), ("reachable", True), ("tls", False)]
    assert "tls_verify" in (steps[-1].hint or "")


@respx.mock
async def test_tls_verify_and_timeout_are_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[Any, Any]] = []
    real = httpx.AsyncClient

    def spy(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        seen.append((kwargs.get("verify"), kwargs.get("timeout")))
        return real(*args, **kwargs)

    respx.get(BASE).respond(200)
    monkeypatch.setattr(httpx, "AsyncClient", spy)
    steps = await RestConnectionProbe().probe(
        rest(tls_verify=False, timeout_seconds=3.5), Secrets(api_key=SECRET)
    )
    assert seen
    assert all(verify is False and timeout == 3.5 for verify, timeout in seen)
    assert "disabled" in steps[2].detail


@respx.mock
@pytest.mark.parametrize("status", [401, 403])
async def test_rejected_credentials_fail_auth(status: int) -> None:
    respx.get(BASE).respond(status)
    step = failing(await RestConnectionProbe().probe(rest(), Secrets(api_key="wrong")))
    assert step.name == "auth"
    assert str(status) in step.detail
    assert step.hint


@respx.mock
async def test_server_error_does_not_pass_auth() -> None:
    respx.get(BASE).respond(503)
    step = failing(await RestConnectionProbe().probe(rest(), Secrets(api_key=SECRET)))
    assert step.name == "auth"
    assert "503" in step.detail


@respx.mock
async def test_missing_credential_fails_auth_without_calling_auth_request() -> None:
    respx.get(BASE).respond(200)
    step = failing(await RestConnectionProbe().probe(rest(), Secrets()))
    assert step.name == "auth"
    assert "API key" in step.detail


@respx.mock
async def test_bearer_token_is_sent() -> None:
    route = respx.get(BASE).respond(200)
    steps = await RestConnectionProbe().probe(
        rest(auth_method=AuthMethod.BEARER), Secrets(token=SECRET)
    )
    assert steps[-1].ok
    assert route.calls.last.request.headers["Authorization"] == f"Bearer {SECRET}"


@respx.mock
@pytest.mark.parametrize("method", [AuthMethod.OAUTH2_CLIENT_CREDENTIALS, AuthMethod.OIDC])
async def test_client_credentials_fetch_a_token_then_authenticate(method: AuthMethod) -> None:
    token = respx.post("https://auth.test/token").respond(200, json={"access_token": "tok-1"})
    api = respx.get(BASE).respond(200)
    profile = rest(auth_method=method, token_url="https://auth.test/token", scope="read")
    steps = await RestConnectionProbe().probe(
        profile, Secrets(client_id="cid", client_secret=SECRET)
    )
    assert steps[-1].ok
    assert api.calls.last.request.headers["Authorization"] == "Bearer tok-1"
    body = token.calls.last.request.content.decode()
    assert "grant_type=client_credentials" in body
    assert "scope=read" in body


@respx.mock
async def test_token_endpoint_rejection_fails_auth() -> None:
    respx.get(BASE).respond(200)
    respx.post("https://auth.test/token").respond(401, json={"error": "invalid_client"})
    profile = rest(
        auth_method=AuthMethod.OAUTH2_CLIENT_CREDENTIALS, token_url="https://auth.test/token"
    )
    step = failing(
        await RestConnectionProbe().probe(profile, Secrets(client_id="c", client_secret=SECRET))
    )
    assert step.name == "auth"
    assert "token endpoint" in step.detail
    assert SECRET not in repr(step)


@respx.mock
async def test_token_url_is_required_for_client_credentials() -> None:
    respx.get(BASE).respond(200)
    profile = rest(auth_method=AuthMethod.OIDC)
    step = failing(
        await RestConnectionProbe().probe(profile, Secrets(client_id="c", client_secret="s"))
    )
    assert step.name == "auth"
    assert "token_url" in step.detail


@respx.mock
async def test_token_endpoint_unreachable_fails_auth() -> None:
    respx.get(BASE).respond(200)
    respx.post("https://auth.test/token").mock(side_effect=httpx.ConnectError("down"))
    profile = rest(
        auth_method=AuthMethod.OAUTH2_CLIENT_CREDENTIALS, token_url="https://auth.test/token"
    )
    step = failing(
        await RestConnectionProbe().probe(profile, Secrets(client_id="c", client_secret="s"))
    )
    assert step.name == "auth"


class FakeOdooClient:
    def __init__(self, outcome: BaseException | None = None) -> None:
        self.outcome = outcome
        self.closed = False

    async def ensure_authenticated(self) -> int:
        if self.outcome:
            raise self.outcome
        return 7

    async def aclose(self) -> None:
        self.closed = True


def odoo(**overrides: Any) -> ConnectionProfile:
    values: dict[str, Any] = {
        "id": None,
        "name": "odoo",
        "type": ProfileType.ODOO,
        "base_url": "https://odoo.test",
        "auth_method": AuthMethod.API_KEY,
        "odoo_db": "prod",
        "odoo_login": "bot",
        "timeout_seconds": 2.0,
    }
    values.update(overrides)
    return ConnectionProfile(**values)


@respx.mock
async def test_odoo_probe_authenticates_with_the_client() -> None:
    respx.get("https://odoo.test").respond(200)
    client = FakeOdooClient()
    built: list[tuple[ConnectionProfile, Secrets]] = []

    def factory(profile: ConnectionProfile, secrets: Secrets) -> FakeOdooClient:
        built.append((profile, secrets))
        return client

    steps = await OdooConnectionProbe(factory).probe(odoo(), Secrets(api_key=SECRET))
    assert names(steps) == [
        ("url_valid", True),
        ("reachable", True),
        ("tls", True),
        ("auth", True),
    ]
    assert "7" in steps[-1].detail
    assert built[0][1].api_key == SECRET
    assert client.closed


@respx.mock
@pytest.mark.parametrize("error", [OdooAuthError("bad"), OdooUnavailable("down")])
async def test_odoo_probe_auth_failures(error: BaseException) -> None:
    respx.get("https://odoo.test").respond(200)
    client = FakeOdooClient(error)
    steps = await OdooConnectionProbe(lambda p, s: client).probe(odoo(), Secrets(api_key=SECRET))
    step = failing(steps)
    assert step.name == "auth"
    assert step.hint
    assert client.closed


@respx.mock
async def test_odoo_probe_stops_before_auth_when_unreachable() -> None:
    respx.get("https://odoo.test").mock(side_effect=httpx.ConnectTimeout("slow"))
    built: list[object] = []

    def factory(profile: ConnectionProfile, secrets: Secrets) -> FakeOdooClient:
        built.append(profile)
        return FakeOdooClient()

    step = failing(await OdooConnectionProbe(factory).probe(odoo(), Secrets(api_key=SECRET)))
    assert step.name == "reachable"
    assert built == []


@respx.mock
async def test_odoo_probe_requires_database_login_and_key() -> None:
    respx.get("https://odoo.test").respond(200)
    probe = OdooConnectionProbe(lambda p, s: FakeOdooClient())
    step = failing(await probe.probe(odoo(odoo_db=None), Secrets(api_key=SECRET)))
    assert step.name == "auth"
    assert "database" in step.detail
    step = failing(await probe.probe(odoo(), Secrets()))
    assert "API key" in step.detail
