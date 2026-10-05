import logging

import pytest
from fastapi.testclient import TestClient

from conector_odoo.domain.entities import CustomerData
from conector_odoo.domain.errors import (
    BatchPartiallyApplied,
    ConnectorError,
    OdooAuthError,
    OdooNotFound,
    OdooPermissionError,
    OdooUnavailable,
    OdooValidationError,
)
from conector_odoo.main import create_app
from tests.api.conftest import API_KEY, ODOO_KEY, Env, make_settings


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (OdooAuthError("bad credentials"), 401, "odoo_auth_error"),
        (OdooPermissionError("no access"), 403, "permission_denied"),
        (OdooNotFound("gone"), 404, "not_found"),
        (OdooValidationError("invalid"), 422, "validation_error"),
        (OdooUnavailable("down"), 502, "odoo_unavailable"),
        (ConnectorError("boom"), 502, "connector_error"),
    ],
)
def test_domain_errors_are_mapped_to_status_and_error_body(
    env: Env, error: ConnectorError, status: int, code: str
) -> None:
    async def failing(customer_id: int) -> None:
        raise error

    env.customers.get = failing  # type: ignore[method-assign]
    response = env.client.get("/customers/1")
    assert response.status_code == status
    assert response.json() == {"error": code, "detail": str(error)}


def test_error_details_never_contain_configured_secrets(env: Env) -> None:
    async def failing(customer_id: int) -> None:
        raise OdooUnavailable(f"upstream said {ODOO_KEY} and {API_KEY}")

    env.customers.get = failing  # type: ignore[method-assign]
    response = env.client.get("/customers/1")
    assert ODOO_KEY not in response.text
    assert response.status_code == 502


def test_validation_errors_do_not_echo_input_values(env: Env) -> None:
    response = env.client.post("/customers", json={"name": "Ada", "email": "secret-value"})
    assert response.status_code == 422
    assert "secret-value" not in response.text


def test_api_key_is_not_required_when_not_configured(env: Env) -> None:
    assert env.client.get("/customers").status_code == 200


def test_api_key_is_required_when_configured(secured_env: Env) -> None:
    response = secured_env.client.get("/customers")
    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"
    assert API_KEY not in response.text


@pytest.mark.parametrize("path", ["/customers", "/customers/1", "/products", "/sale-orders/1"])
def test_every_data_endpoint_is_protected(secured_env: Env, path: str) -> None:
    assert secured_env.client.get(path).status_code == 401
    assert secured_env.client.get(path, headers={"X-API-Key": "wrong"}).status_code == 401
    assert secured_env.client.get(path, headers={"X-API-Key": API_KEY}).status_code != 401


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/customers"),
        ("PATCH", "/customers/1"),
        ("POST", "/sale-orders"),
        ("POST", "/sale-orders/1/confirm"),
    ],
)
def test_write_endpoints_are_protected(secured_env: Env, method: str, path: str) -> None:
    assert secured_env.client.request(method, path, json={}).status_code == 401


def test_wrong_api_key_is_rejected_and_correct_one_accepted(secured_env: Env) -> None:
    bad = secured_env.client.get("/customers", headers={"X-API-Key": "nope"})
    assert bad.status_code == 401
    good = secured_env.client.get("/customers", headers={"X-API-Key": API_KEY})
    assert good.status_code == 200


def test_health_is_public_even_when_api_key_is_configured(secured_env: Env) -> None:
    assert secured_env.client.get("/health").status_code == 200


def test_health_ok(env: Env) -> None:
    response = env.client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "odoo": "reachable",
        "uid": 42,
        "protocol": "jsonrpc",
    }


@pytest.mark.parametrize("error", [OdooUnavailable("down"), OdooAuthError("bad key")])
def test_health_degraded_on_connector_error(env: Env, error: ConnectorError) -> None:
    env.odoo.result = error
    response = env.client.get("/health")
    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "detail": str(error)}


def test_health_degraded_detail_hides_secrets(env: Env) -> None:
    env.odoo.result = OdooUnavailable(f"failed with {ODOO_KEY}")
    response = env.client.get("/health")
    assert response.status_code == 503
    assert ODOO_KEY not in response.text


def test_request_id_is_generated_and_echoed(env: Env) -> None:
    generated = env.client.get("/health").headers["x-request-id"]
    assert len(generated) >= 16
    echoed = env.client.get("/health", headers={"X-Request-ID": "abc-123"})
    assert echoed.headers["x-request-id"] == "abc-123"


def test_unsafe_request_id_is_replaced(env: Env) -> None:
    response = env.client.get("/health", headers={"X-Request-ID": "bad id\twith spaces"})
    assert response.headers["x-request-id"] != "bad id\twith spaces"


def test_requests_are_logged_without_secrets(
    secured_env: Env, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="conector_odoo.request"):
        secured_env.client.get("/customers", headers={"X-API-Key": API_KEY, "X-Request-ID": "r1"})
    record = next(r for r in caplog.records if r.name == "conector_odoo.request")
    assert (record.method, record.path, record.status_code, record.request_id) == (
        "GET",
        "/customers",
        200,
        "r1",
    )
    assert isinstance(record.duration_ms, float)
    assert API_KEY not in caplog.text


def test_create_app_defaults_to_settings_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ODOO_URL", "https://odoo.test")
    monkeypatch.setenv("ODOO_DB", "db")
    monkeypatch.setenv("ODOO_USER", "bot")
    monkeypatch.setenv("ODOO_API_KEY", "odoo-secret-key-0123")
    monkeypatch.setenv("WEBHOOK_SECRET", "whsec-test-secret-123")
    monkeypatch.setenv("CONNECTOR_API_KEY", API_KEY)
    monkeypatch.setenv("IDEMPOTENCY_DB_PATH", ":memory:")
    monkeypatch.setenv("ADMIN_DB_PATH", ":memory:")
    from conector_odoo.config import get_settings

    get_settings.cache_clear()
    try:
        with TestClient(create_app()) as client:
            assert client.get("/customers").status_code == 401
    finally:
        get_settings.cache_clear()


def test_lifespan_closes_the_odoo_client() -> None:
    app = create_app(make_settings())
    with TestClient(app):
        client = app.state.container.odoo_client
        assert client is not None
    transport = client._transport
    assert transport._client.is_closed


def test_batch_partially_applied_maps_to_502_with_created_ids(env: Env) -> None:
    async def boom(self: object, data: CustomerData) -> None:
        raise BatchPartiallyApplied([5, 6], 1, "chunk 1 failed: timeout")

    env.customers.create = boom.__get__(env.customers)  # type: ignore[method-assign]
    response = env.client.post("/customers", json={"name": "Ada"})
    assert response.status_code == 502
    assert response.json() == {
        "error": "batch_partially_applied",
        "detail": "chunk 1 failed: timeout",
        "created_ids": [5, 6],
        "failed_chunk": 1,
    }
