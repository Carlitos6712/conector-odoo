"""The policy is applied at every place the app contacts a user-supplied URL."""

import asyncio
from typing import Any

import pytest

from conector_odoo.config import Settings
from conector_odoo.domain.errors import OpenApiImportError, OutboundUrlBlocked
from conector_odoo.domain.outbound import DEFAULT_POLICY, OutboundMode, OutboundPolicy
from conector_odoo.domain.profiles import AuthMethod, ConnectionProfile, ProfileType, Secrets
from conector_odoo.infrastructure.net import guard
from conector_odoo.infrastructure.odoo.factory import build_odoo_endpoint
from conector_odoo.infrastructure.odoo.json2 import Json2Transport
from conector_odoo.infrastructure.odoo.jsonrpc import JsonRpcTransport
from conector_odoo.infrastructure.odoo.xmlrpc import XmlRpcTransport
from conector_odoo.infrastructure.openapi.importer import OpenApiImporter
from conector_odoo.infrastructure.openapi.loader import fetch_document
from conector_odoo.infrastructure.profiles.odoo_probe import OdooConnectionProbe
from conector_odoo.infrastructure.profiles.rest_probe import RestConnectionProbe
from conector_odoo.infrastructure.rest.auth import build_authenticator
from conector_odoo.infrastructure.rest.http import RestHttpClient
from tests.api.conftest import make_settings

METADATA = "http://169.254.169.254"
STRICT = OutboundPolicy(OutboundMode.STRICT)


def rest_profile(**overrides: Any) -> ConnectionProfile:
    values: dict[str, Any] = {
        "id": None,
        "name": "p",
        "type": ProfileType.REST,
        "base_url": "https://api.test",
        "auth_method": AuthMethod.BEARER,
        "timeout_seconds": 2.0,
    }
    values.update(overrides)
    return ConnectionProfile(**values)


def odoo_profile(base_url: str) -> ConnectionProfile:
    return ConnectionProfile(
        id=None,
        name="o",
        type=ProfileType.ODOO,
        base_url=base_url,
        auth_method=AuthMethod.API_KEY,
        odoo_db="db",
        odoo_login="bot",
        timeout_seconds=2.0,
    )


def never_resolve(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    async def boom(host: str, port: int) -> list[str]:
        calls.append(host)
        raise AssertionError("DNS must not be consulted for a literal blocked address")

    monkeypatch.setattr(guard, "resolve_host", boom)
    return calls


# -- settings -----------------------------------------------------------------------------------


def test_settings_default_to_the_default_policy() -> None:
    settings = make_settings()
    assert settings.outbound_url_policy == "default"
    assert settings.outbound_allowed_hosts == ""
    assert settings.outbound_policy() == DEFAULT_POLICY


def test_settings_build_a_strict_policy_with_an_allow_list() -> None:
    settings = make_settings(
        outbound_url_policy="strict", outbound_allowed_hosts="Odoo.lan, 10.0.0.5"
    )
    assert settings.outbound_policy() == OutboundPolicy(
        OutboundMode.STRICT, frozenset({"odoo.lan", "10.0.0.5"})
    )


def test_settings_reject_an_unknown_policy_mode() -> None:
    with pytest.raises(ValueError):
        Settings(_env_file=None, outbound_url_policy="lax")  # type: ignore[call-arg]


# -- OpenAPI import -----------------------------------------------------------------------------


async def test_openapi_fetch_refuses_the_metadata_address(monkeypatch: pytest.MonkeyPatch) -> None:
    never_resolve(monkeypatch)
    with pytest.raises(OutboundUrlBlocked):
        await fetch_document(f"{METADATA}/openapi.json")
    with pytest.raises(OutboundUrlBlocked):
        await OpenApiImporter().import_url(f"{METADATA}/openapi.json")


async def test_openapi_fetch_checks_every_redirect_hop(monkeypatch: pytest.MonkeyPatch) -> None:
    # Same host name on every hop (the existing redirect rule) but the second lookup now points at
    # the metadata address: the hop is a new connection and is validated again.
    answers = [["127.0.0.1"], ["169.254.169.254"]]
    port = await _redirecting_origin()

    async def resolve(host: str, p: int) -> list[str]:
        return answers.pop(0) if len(answers) > 1 else answers[0]

    monkeypatch.setattr(guard, "resolve_host", resolve)
    with pytest.raises(OutboundUrlBlocked):
        await fetch_document(f"http://docs.test:{port}/start")


async def test_openapi_fetch_in_strict_mode_blocks_loopback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(OutboundUrlBlocked):
        await fetch_document("http://127.0.0.1:9/openapi.json", policy=STRICT)


async def test_openapi_non_http_scheme_keeps_its_import_error() -> None:
    with pytest.raises(OpenApiImportError):
        await fetch_document("file:///etc/passwd")


async def _redirecting_origin() -> int:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readuntil(b"\r\n\r\n")
        writer.write(
            b"HTTP/1.1 302 Found\r\nLocation: /next\r\nContent-Length: 0\r\n"
            b"Connection: close\r\n\r\n"
        )
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    asyncio.get_running_loop().call_later(5, server.close)
    return int(server.sockets[0].getsockname()[1])


# -- REST: base url, token url, issuer url ------------------------------------------------------


async def test_rest_client_refuses_a_link_local_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    never_resolve(monkeypatch)
    prof = rest_profile(base_url=METADATA)
    auth = build_authenticator(prof, Secrets(token="tok-secret-value-123"))
    http = RestHttpClient(prof.base_url, auth)
    with pytest.raises(OutboundUrlBlocked):
        await http.request("GET", "/latest/meta-data")
    await http.aclose()


async def test_rest_client_refuses_a_link_local_token_url(monkeypatch: pytest.MonkeyPatch) -> None:
    never_resolve(monkeypatch)
    prof = rest_profile(
        auth_method=AuthMethod.OAUTH2_CLIENT_CREDENTIALS, token_url=f"{METADATA}/token"
    )
    auth = build_authenticator(prof, Secrets(client_id="id", client_secret="secret-value-123"))
    http = RestHttpClient(prof.base_url, auth)
    with pytest.raises(OutboundUrlBlocked):
        await http.request("GET", "/items")
    await http.aclose()


async def test_rest_client_refuses_a_link_local_issuer_url(monkeypatch: pytest.MonkeyPatch) -> None:
    never_resolve(monkeypatch)
    prof = rest_profile(auth_method=AuthMethod.OIDC)
    auth = build_authenticator(
        prof, Secrets(client_id="id", client_secret="secret-value-123"), issuer_url=METADATA
    )
    http = RestHttpClient(prof.base_url, auth)
    with pytest.raises(OutboundUrlBlocked):
        await http.request("GET", "/items")
    await http.aclose()


async def test_rest_client_in_strict_mode_blocks_a_private_target() -> None:
    prof = rest_profile(base_url="http://10.1.2.3")
    auth = build_authenticator(prof, Secrets(token="tok-secret-value-123"))
    http = RestHttpClient(prof.base_url, auth, policy=STRICT)
    with pytest.raises(OutboundUrlBlocked):
        await http.request("GET", "/items")
    await http.aclose()


# -- probes -------------------------------------------------------------------------------------


async def test_rest_probe_reports_a_blocked_url_as_a_failed_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    never_resolve(monkeypatch)
    steps = await RestConnectionProbe().probe(
        rest_profile(base_url=METADATA), Secrets(token="tok-secret-value-123")
    )
    assert [(s.name, s.ok) for s in steps] == [("url_valid", True), ("reachable", False)]
    assert "URL policy" in steps[-1].detail
    assert "169.254" not in steps[-1].detail


async def test_rest_probe_blocks_a_link_local_token_url(monkeypatch: pytest.MonkeyPatch) -> None:
    # Reachable base URL (stubbed DNS to a listening loopback is not needed: the token step fails).
    never_resolve(monkeypatch)
    prof = rest_profile(
        base_url="http://127.0.0.1:9",
        auth_method=AuthMethod.OAUTH2_CLIENT_CREDENTIALS,
        token_url=f"{METADATA}/token",
    )
    steps = await RestConnectionProbe(policy=STRICT).probe(
        prof, Secrets(client_id="id", client_secret="secret-value-123")
    )
    assert not steps[-1].ok and "URL policy" in steps[-1].detail


async def test_odoo_probe_reports_a_blocked_url(monkeypatch: pytest.MonkeyPatch) -> None:
    never_resolve(monkeypatch)
    steps = await OdooConnectionProbe().probe(odoo_profile(METADATA), Secrets(api_key="k" * 20))
    assert not steps[-1].ok and "URL policy" in steps[-1].detail


# -- Odoo transports ----------------------------------------------------------------------------


@pytest.mark.parametrize("protocol", ["jsonrpc", "json2", "xmlrpc"])
async def test_odoo_profile_endpoint_refuses_a_link_local_url(
    protocol: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    never_resolve(monkeypatch)
    endpoint = build_odoo_endpoint(
        odoo_profile(METADATA), Secrets(api_key="k" * 20), protocol=protocol, max_retries=0
    )
    with pytest.raises(OutboundUrlBlocked):
        await endpoint.describe("res.partner")
    await endpoint.aclose()


async def test_odoo_profile_endpoint_follows_the_strict_policy() -> None:
    endpoint = build_odoo_endpoint(
        odoo_profile("http://10.9.9.9"),
        Secrets(api_key="k" * 20),
        max_retries=0,
        policy=STRICT,
    )
    with pytest.raises(OutboundUrlBlocked):
        await endpoint.describe("res.partner")
    await endpoint.aclose()


async def test_transports_without_a_policy_keep_the_legacy_client() -> None:
    # The env-configured Odoo of the data API is operator-controlled: no policy unless asked.
    assert JsonRpcTransport("http://x", "db", "u", "k" * 20)._client._transport is not None
    assert not isinstance(
        JsonRpcTransport("http://x", "db", "u", "k" * 20)._client._transport, guard.GuardedTransport
    )
    assert not isinstance(
        Json2Transport("http://x", "db", "u", "k" * 20)._client._transport, guard.GuardedTransport
    )
    assert XmlRpcTransport("http://x", "db", "u", "k" * 20)._policy is None
