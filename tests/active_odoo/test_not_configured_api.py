"""Without any Odoo connection the app starts, and the legacy data API answers 503."""

import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from conector_odoo.domain.active_odoo import OdooSource
from conector_odoo.main import create_app
from tests.api.conftest import API_KEY, make_settings
from tests.api.test_webhooks import payload, signed_headers


def bare_settings(**overrides: Any) -> Any:
    values: dict[str, Any] = {
        "odoo_url": None,
        "odoo_db": None,
        "odoo_user": None,
        "odoo_api_key": None,
    }
    values.update(overrides)
    return make_settings(**values)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(bare_settings())) as test_client:
        yield test_client


def test_the_app_starts_without_any_odoo_environment(client: TestClient) -> None:
    provider = client.app.state.container.odoo  # type: ignore[attr-defined]
    assert provider.current is None


def test_livez_stays_200(client: TestClient) -> None:
    assert client.get("/livez").status_code == 200


def test_health_reports_not_configured_without_failing(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["odoo"] == "not_configured"
    assert body["uid"] is None


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/customers", None),
        ("GET", "/customers/1", None),
        ("GET", "/customers/export", None),
        ("POST", "/customers", {"name": "Ada"}),
        ("POST", "/customers/bulk", {"items": [{"name": "Ada"}]}),
        ("GET", "/products", None),
        ("GET", "/sale-orders/1", None),
    ],
)
def test_legacy_routes_answer_503_odoo_not_configured(
    client: TestClient, method: str, path: str, body: dict[str, Any] | None
) -> None:
    response = client.request(method, path, json=body)
    assert response.status_code == 503, response.text
    error = response.json()
    assert error["error"] == "odoo_not_configured"
    assert "admin" in error["detail"].lower()


def test_authentication_still_comes_before_the_503() -> None:
    with TestClient(create_app(bare_settings(connector_api_key=API_KEY))) as secured:
        assert secured.get("/customers").status_code == 401
        ok = secured.get("/customers", headers={"X-API-Key": API_KEY})
        assert ok.status_code == 503


def test_the_webhook_intake_does_not_need_odoo(client: TestClient) -> None:
    raw = json.dumps(payload()).encode()
    response = client.post("/webhooks/odoo", content=raw, headers=signed_headers(raw))
    assert response.status_code == 202


def test_legacy_env_still_builds_the_connection_at_startup() -> None:
    app = create_app(make_settings())  # ODOO_* all present
    with TestClient(app):
        current = app.state.container.odoo.current
        assert current is not None and current.source is OdooSource.ENV
        assert app.state.container.odoo_client is current.client


def test_requests_hold_a_lease_while_they_run_and_release_it_after() -> None:
    app = create_app(make_settings())
    with TestClient(app) as test_client:
        current = app.state.container.odoo.current
        assert test_client.get("/livez").status_code == 200
        assert current.leases == 0
        test_client.get("/customers")  # Odoo is unreachable here: the call fails, not hangs
        assert current.leases == 0
