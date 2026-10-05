import json
from typing import Any

import httpx
import pytest
import respx

from conector_odoo.domain.errors import OpenApiImportError
from conector_odoo.infrastructure.openapi import loader
from conector_odoo.infrastructure.openapi.importer import OpenApiImporter

SPEC = {
    "openapi": "3.0.0",
    "paths": {"/things": {"get": {"responses": {"200": {"description": "ok"}}}}},
}
URL = "https://api.example.com/openapi.json"


@respx.mock
async def test_fetch_and_import_from_url() -> None:
    respx.get(URL).respond(200, json=SPEC)
    report = await OpenApiImporter().import_url(URL)
    assert [c.name for c in report.candidates] == ["things"]


@respx.mock
async def test_headers_are_sent_only_when_passed() -> None:
    route = respx.get(URL).respond(200, json=SPEC)
    await OpenApiImporter().import_url(URL)
    assert "x-tenant" not in route.calls.last.request.headers
    await OpenApiImporter().import_url(URL, headers={"X-Tenant": "acme"})
    assert route.calls.last.request.headers["x-tenant"] == "acme"


@respx.mock
async def test_tls_verify_is_passed_through_only_when_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    respx.get(URL).respond(200, json=SPEC)
    seen: list[Any] = []
    real = httpx.AsyncClient

    def spy(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        seen.append(kwargs.get("verify"))
        return real(*args, **kwargs)

    monkeypatch.setattr(loader.httpx, "AsyncClient", spy)
    await OpenApiImporter().import_url(URL)
    await OpenApiImporter().import_url(URL, tls_verify=False)
    assert seen == [True, False]


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/x",
        "javascript:alert(1)",
        "//example.com/x",
        "",
        "http:///x",
    ],
)
async def test_only_http_and_https_urls_are_accepted(url: str) -> None:
    with pytest.raises(OpenApiImportError, match="http"):
        await OpenApiImporter().import_url(url)


@respx.mock
async def test_response_size_cap_stops_a_streamed_download() -> None:
    respx.get(URL).respond(200, content=b"x" * 5000)
    with pytest.raises(OpenApiImportError, match="larger"):
        await OpenApiImporter(max_bytes=1000).import_url(URL)


@respx.mock
async def test_declared_content_length_over_the_cap_is_rejected_early() -> None:
    respx.get(URL).respond(200, content=b"{}", headers={"content-length": "999999999"})
    with pytest.raises(OpenApiImportError, match="larger"):
        await OpenApiImporter(max_bytes=1000).import_url(URL)


@respx.mock
async def test_http_errors_and_network_failures_are_import_errors() -> None:
    respx.get(URL).respond(404)
    with pytest.raises(OpenApiImportError, match="404"):
        await OpenApiImporter().import_url(URL)
    respx.get(URL).mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(OpenApiImportError, match="reach"):
        await OpenApiImporter().import_url(URL)


@respx.mock
async def test_url_import_passes_base_path() -> None:
    spec = {**SPEC, "paths": {"/api/things": SPEC["paths"]["/things"]}}  # type: ignore[index]
    respx.get(URL).respond(200, content=json.dumps(spec).encode())
    report = await OpenApiImporter().import_url(URL, base_path="/api")
    assert report.candidates[0].list_endpoint is not None
    assert report.candidates[0].list_endpoint.path == "/things"


# -- redirects: followed by hand, one hop at a time, never off the original host -----------------


@respx.mock
async def test_a_redirect_on_the_same_host_is_followed() -> None:
    respx.get(URL).respond(302, headers={"location": "/v2/openapi.json"})
    final = respx.get("https://api.example.com/v2/openapi.json").respond(200, json=SPEC)
    report = await OpenApiImporter().import_url(URL)
    assert [c.name for c in report.candidates] == ["things"] and final.called


@respx.mock
async def test_a_redirect_to_another_host_is_refused_without_contacting_it() -> None:
    respx.get(URL).respond(302, headers={"location": "http://169.254.169.254/latest/meta-data"})
    internal = respx.get("http://169.254.169.254/latest/meta-data").respond(200, json=SPEC)
    with pytest.raises(OpenApiImportError, match="redirect"):
        await OpenApiImporter().import_url(URL)
    assert not internal.called


@respx.mock
async def test_headers_never_follow_a_redirect_off_the_host() -> None:
    respx.get(URL).respond(301, headers={"location": "https://evil.example.net/spec.json"})
    elsewhere = respx.get("https://evil.example.net/spec.json").respond(200, json=SPEC)
    with pytest.raises(OpenApiImportError, match="redirect"):
        await OpenApiImporter().import_url(URL, headers={"Authorization": "Bearer secret"})
    assert not elsewhere.called


@respx.mock
async def test_an_https_to_http_downgrade_is_refused() -> None:
    respx.get(URL).respond(302, headers={"location": "http://api.example.com/openapi.json"})
    plain = respx.get("http://api.example.com/openapi.json").respond(200, json=SPEC)
    with pytest.raises(OpenApiImportError, match="redirect"):
        await OpenApiImporter().import_url(URL)
    assert not plain.called


@respx.mock
async def test_an_http_to_https_upgrade_on_the_same_host_is_allowed() -> None:
    respx.get("http://api.example.com/openapi.json").respond(
        301, headers={"location": "https://api.example.com/openapi.json"}
    )
    respx.get(URL).respond(200, json=SPEC)
    report = await OpenApiImporter().import_url("http://api.example.com/openapi.json")
    assert report.candidates


@respx.mock
async def test_redirect_loops_and_missing_locations_are_import_errors() -> None:
    respx.get(URL).respond(302, headers={"location": URL})
    with pytest.raises(OpenApiImportError, match="redirect"):
        await OpenApiImporter().import_url(URL)
    respx.get(URL).respond(302)
    with pytest.raises(OpenApiImportError, match="redirect"):
        await OpenApiImporter().import_url(URL)
