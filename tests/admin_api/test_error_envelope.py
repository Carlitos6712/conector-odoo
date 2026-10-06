from typing import Any

from fastapi.testclient import TestClient

from conector_odoo.main import create_app
from tests.admin_api.conftest import ADMIN_PASSWORD, ADMIN_USER, AdminEnv, admin_settings


def test_unexpected_errors_become_a_plain_500_without_details() -> None:
    app = create_app(admin_settings())
    with TestClient(app, raise_server_exceptions=False) as client:
        env = AdminEnv(client)
        env.login()

        async def boom(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("leaky /home/carlos/secret.db sk-live-123 Traceback")

        app.state.admin.profiles.list.execute = boom
        response = env.get("/admin/api/profiles")
    assert response.status_code == 500
    assert response.json() == {"error": "internal_error", "detail": "internal server error"}
    assert "carlos" not in response.text and "sk-live" not in response.text


def test_every_error_uses_the_error_detail_envelope(admin_env: AdminEnv) -> None:
    responses = [
        admin_env.client.get("/admin/api/profiles"),  # 401
        admin_env.client.post("/admin/api/auth/login", json={}),  # 422
        admin_env.client.post(
            "/admin/api/auth/login", json={"username": ADMIN_USER, "password": "nope-nope-nope"}
        ),  # 401
    ]
    admin_env.login(ADMIN_USER, ADMIN_PASSWORD)
    responses += [
        admin_env.get("/admin/api/profiles/999"),
        admin_env.post("/admin/api/users", json={}),
    ]
    for response in responses:
        assert response.status_code >= 400
        assert set(response.json()) >= {"error", "detail"}
        assert "Traceback" not in response.text
