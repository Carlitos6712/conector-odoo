from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from conector_odoo.main import create_app
from tests.admin_api.conftest import ADMIN_PASSWORD, ADMIN_USER, admin_settings

LOGIN = "/admin/api/auth/login"
BAD = "nope-nope-nope"


def make_client(**settings: object) -> Iterator[TestClient]:
    values: dict[str, object] = {
        "admin_login_ip_max_failures": 3,
        "admin_login_max_failures": 50,
        "admin_login_ip_window_seconds": 600,
    }
    values.update(settings)
    with TestClient(create_app(admin_settings(**values))) as client:
        yield client


@pytest.fixture
def client() -> Iterator[TestClient]:
    yield from make_client()


@pytest.fixture
def proxied() -> Iterator[TestClient]:
    yield from make_client(trusted_proxy_count=1)


def fail(client: TestClient, username: str = "ghost", **headers: str) -> None:
    response = client.post(LOGIN, json={"username": username, "password": BAD}, headers=headers)
    assert response.status_code == 401


def test_defaults_match_the_documented_values() -> None:
    settings = admin_settings()
    assert settings.admin_login_ip_max_failures == 20
    assert settings.admin_login_ip_window_seconds == 900
    assert settings.trusted_proxy_count == 0


def test_ip_is_throttled_with_429_retry_after_and_the_generic_body(client: TestClient) -> None:
    for name in ("a", "b", "c"):
        fail(client, name)
    limited = client.post(LOGIN, json={"username": ADMIN_USER, "password": ADMIN_PASSWORD})
    assert limited.status_code == 429
    assert limited.json()["error"] == "too_many_attempts"
    assert 0 < int(limited.headers["retry-after"]) <= 600
    assert "set-cookie" not in limited.headers


def test_throttle_body_is_identical_for_real_and_unknown_users(client: TestClient) -> None:
    for name in ("a", "b", "c"):
        fail(client, name)
    real = client.post(LOGIN, json={"username": ADMIN_USER, "password": BAD})
    ghost = client.post(LOGIN, json={"username": "ghost", "password": BAD})
    assert real.status_code == ghost.status_code == 429
    assert real.json() == ghost.json()


def test_password_change_failures_are_throttled_per_ip(client: TestClient) -> None:
    csrf = client.post(LOGIN, json={"username": ADMIN_USER, "password": ADMIN_PASSWORD}).json()[
        "csrf_token"
    ]
    body = {"current_password": BAD, "new_password": "another-password-123"}
    for _ in range(3):
        resp = client.post("/admin/api/auth/password", json=body, headers={"X-CSRF-Token": csrf})
        assert resp.status_code == 422
    resp = client.post("/admin/api/auth/password", json=body, headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 429
    assert int(resp.headers["retry-after"]) > 0


def test_forwarded_header_is_ignored_without_trusted_proxies(client: TestClient) -> None:
    # Rotating X-Forwarded-For must not evade the throttle when no proxy is trusted.
    for i in range(3):
        fail(client, **{"X-Forwarded-For": f"198.51.100.{i}"})
    blocked = client.post(
        LOGIN,
        json={"username": "ghost", "password": BAD},
        headers={"X-Forwarded-For": "192.0.2.77"},
    )
    assert blocked.status_code == 429


def test_trusted_proxy_uses_the_right_most_entry(proxied: TestClient) -> None:
    # Left-most values are attacker-controlled and must not matter; the right-most is the client.
    for i in range(3):
        fail(proxied, **{"X-Forwarded-For": f"10.9.9.{i}, 203.0.113.50"})
    same_client = proxied.post(
        LOGIN,
        json={"username": "ghost", "password": BAD},
        headers={"X-Forwarded-For": "1.1.1.1, 203.0.113.50"},
    )
    assert same_client.status_code == 429
    other_client = proxied.post(
        LOGIN,
        json={"username": "ghost", "password": BAD},
        headers={"X-Forwarded-For": "203.0.113.50, 203.0.113.51"},
    )
    assert other_client.status_code == 401  # a different right-most entry is a different client


def test_trusted_proxy_without_the_header_falls_back_to_the_peer(proxied: TestClient) -> None:
    for _ in range(3):
        fail(proxied)
    assert proxied.post(LOGIN, json={"username": "ghost", "password": BAD}).status_code == 429
