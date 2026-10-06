from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from conector_odoo.config import Settings
from conector_odoo.main import create_app
from tests.api.conftest import make_settings

ADMIN_USER = "root"
ADMIN_PASSWORD = "root-password-123"
OPERATOR_USER = "viewer"
OPERATOR_PASSWORD = "viewer-password-123"
ENCRYPTION_KEY = "o3tqmQ5kYpq3m4Yq4o4oWc6G8jzC3xUj0yq7a6c0P2U="  # valid Fernet key, test only


def admin_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "admin_bootstrap_user": ADMIN_USER,
        "admin_bootstrap_password": ADMIN_PASSWORD,
        "admin_cookie_secure": False,  # TestClient talks plain HTTP
        "admin_argon2_time_cost": 1,
        "admin_argon2_memory_kib": 8,
        "admin_argon2_parallelism": 1,
        "sync_scheduler_enabled": False,
        "encryption_key": ENCRYPTION_KEY,
    }
    values.update(overrides)
    return make_settings(**values)


class AdminEnv:
    """A running app plus helpers to sign in as the bootstrap admin or an operator."""

    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.csrf = ""

    def login(self, username: str = ADMIN_USER, password: str = ADMIN_PASSWORD) -> str:
        response = self.client.post(
            "/admin/api/auth/login", json={"username": username, "password": password}
        )
        assert response.status_code == 200, response.text
        self.csrf = str(response.json()["csrf_token"])
        return self.csrf

    @property
    def headers(self) -> dict[str, str]:
        return {"X-CSRF-Token": self.csrf}

    def request(self, method: str, url: str, **kwargs: Any) -> Any:
        return self.client.request(method, url, headers=self.headers, **kwargs)

    def get(self, url: str, **kwargs: Any) -> Any:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> Any:
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> Any:
        return self.request("PUT", url, **kwargs)

    def patch(self, url: str, **kwargs: Any) -> Any:
        return self.request("PATCH", url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> Any:
        return self.request("DELETE", url, **kwargs)

    def logout(self) -> None:
        self.client.post("/admin/api/auth/logout", headers=self.headers)
        self.client.cookies.clear()
        self.csrf = ""

    def create_operator(self) -> None:
        response = self.post(
            "/admin/api/users",
            json={"username": OPERATOR_USER, "password": OPERATOR_PASSWORD, "role": "operator"},
        )
        assert response.status_code == 201, response.text


@pytest.fixture
def admin_env() -> Iterator[AdminEnv]:
    app = create_app(admin_settings())
    with TestClient(app) as client:
        yield AdminEnv(client)


@pytest.fixture
def admin(admin_env: AdminEnv) -> AdminEnv:
    admin_env.login()
    return admin_env


@pytest.fixture
def operator(admin_env: AdminEnv) -> AdminEnv:
    admin_env.login()
    admin_env.create_operator()
    admin_env.logout()
    admin_env.login(OPERATOR_USER, OPERATOR_PASSWORD)
    return admin_env
