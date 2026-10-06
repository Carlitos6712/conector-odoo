import pytest
from fastapi.testclient import TestClient

from conector_odoo.config import Settings
from conector_odoo.domain.auth import Role
from conector_odoo.main import create_app
from tests.admin_api.conftest import admin_settings


def test_the_flag_defaults_to_off() -> None:
    assert admin_settings().admin_auth_disabled is False


def test_the_flag_is_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_AUTH_DISABLED", "true")
    monkeypatch.setenv("WEBHOOK_SECRET", "whsec-test-secret-123")
    assert Settings(_env_file=None).admin_auth_disabled is True

def test_with_the_flag_off_anonymous_requests_are_still_rejected() -> None:
    with TestClient(create_app(admin_settings(admin_auth_disabled=False))) as client:
        assert client.get("/admin/api/auth/me").status_code == 401
        assert client.get("/admin/api/profiles").status_code == 401


def test_with_the_flag_on_a_protected_read_needs_no_login() -> None:
    with TestClient(create_app(admin_settings(admin_auth_disabled=True))) as client:
        assert client.get("/admin/api/profiles").status_code == 200


def test_with_the_flag_on_an_admin_mutation_needs_neither_cookie_nor_csrf() -> None:
    with TestClient(create_app(admin_settings(admin_auth_disabled=True))) as client:
        created = client.post(
            "/admin/api/users",
            json={"username": "viewer", "password": "viewer-password-123", "role": "operator"},
        )
        assert created.status_code == 201, created.text


def test_with_the_flag_on_me_returns_an_admin_and_a_csrf_token() -> None:
    with TestClient(create_app(admin_settings(admin_auth_disabled=True))) as client:
        response = client.get("/admin/api/auth/me")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["user"]["role"] == Role.ADMIN.value
        assert body["csrf_token"]


def test_with_the_flag_on_bootstrap_creates_no_user() -> None:
    app = create_app(admin_settings(admin_auth_disabled=True))
    with TestClient(app) as client:
        users = client.get("/admin/api/users").json()
        assert users == [] or users.get("items") == []


def test_with_the_flag_on_startup_logs_one_warning(capsys: pytest.CaptureFixture[str]) -> None:
    with TestClient(create_app(admin_settings(admin_auth_disabled=True))):
        pass
    lines = [
        ln for ln in capsys.readouterr().err.splitlines() if "authentication is disabled" in ln
    ]
    assert len(lines) == 1
    assert '"level": "WARNING"' in lines[0]
