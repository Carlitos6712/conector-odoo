from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from conector_odoo.main import create_app
from tests.admin_api.conftest import (
    ADMIN_PASSWORD,
    ADMIN_USER,
    AdminEnv,
    admin_settings,
)

LOGIN = "/admin/api/auth/login"


def test_login_sets_a_hardened_cookie_and_returns_the_csrf_token(admin_env: AdminEnv) -> None:
    response = admin_env.client.post(
        LOGIN, json={"username": ADMIN_USER, "password": ADMIN_PASSWORD}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["user"] == {
        "id": 1,
        "username": ADMIN_USER,
        "role": "admin",
        "created_at": body["user"]["created_at"],
    }
    assert body["csrf_token"] and body["expires_at"]
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/admin/api" in cookie
    assert "secure" not in cookie.replace("secure=", "")  # test settings disable it
    assert response.headers["cache-control"] == "no-store"


def test_cookie_is_secure_by_default() -> None:
    settings = admin_settings(admin_cookie_secure=True)
    with TestClient(create_app(settings)) as client:
        response = client.post(LOGIN, json={"username": ADMIN_USER, "password": ADMIN_PASSWORD})
    assert "secure" in response.headers["set-cookie"].lower().split("; ")


def test_wrong_password_and_unknown_user_are_indistinguishable(admin_env: AdminEnv) -> None:
    wrong = admin_env.client.post(
        LOGIN, json={"username": ADMIN_USER, "password": "nope-nope-nope"}
    )
    unknown = admin_env.client.post(LOGIN, json={"username": "ghost", "password": "nope-nope-nope"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    assert wrong.json()["error"] == "invalid_credentials"
    assert "set-cookie" not in wrong.headers


def test_lockout_returns_429_with_retry_after(admin_env: AdminEnv) -> None:
    for _ in range(5):
        admin_env.client.post(LOGIN, json={"username": ADMIN_USER, "password": "nope-nope-nope"})
    locked = admin_env.client.post(LOGIN, json={"username": ADMIN_USER, "password": ADMIN_PASSWORD})
    assert locked.status_code == 429
    assert locked.json()["error"] == "too_many_attempts"
    assert int(locked.headers["retry-after"]) > 0


def test_me_requires_a_session_and_returns_the_user(admin_env: AdminEnv) -> None:
    anonymous = admin_env.client.get("/admin/api/auth/me")
    assert anonymous.status_code == 401
    assert anonymous.json()["error"] == "unauthenticated"
    csrf = admin_env.login()
    me = admin_env.client.get("/admin/api/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["username"] == ADMIN_USER and me.json()["csrf_token"] == csrf


def test_forged_cookie_is_rejected(admin_env: AdminEnv) -> None:
    admin_env.client.cookies.set("admin_session", "forged", path="/admin/api")
    assert admin_env.client.get("/admin/api/auth/me").status_code == 401


def test_logout_destroys_the_session_server_side(admin: AdminEnv) -> None:
    token = admin.client.cookies.get("admin_session")
    assert token
    assert admin.post("/admin/api/auth/logout").status_code == 204
    admin.client.cookies.set("admin_session", token, path="/admin/api")  # replay the old cookie
    assert admin.client.get("/admin/api/auth/me").status_code == 401


def test_logout_without_a_session_is_harmless(admin_env: AdminEnv) -> None:
    assert admin_env.client.post("/admin/api/auth/logout").status_code == 204


def test_relogin_rotates_the_session_and_invalidates_the_old_cookie(admin: AdminEnv) -> None:
    old = admin.client.cookies.get("admin_session")
    assert old
    admin.login()  # the browser still sends the old cookie
    new = admin.client.cookies.get("admin_session")
    assert new and new != old
    admin.client.cookies.set("admin_session", old, path="/admin/api")
    assert admin.client.get("/admin/api/auth/me").status_code == 401


def test_expired_session_is_rejected() -> None:
    settings = admin_settings(admin_session_ttl_seconds=60)
    app = create_app(settings)
    with TestClient(app) as client:
        env = AdminEnv(client)
        env.login()
        # Age the session in the store: expiry is enforced server-side, not by the cookie.
        app.state.admin_db.execute(
            "UPDATE admin_sessions SET expires_at = '2000-01-01T00:00:00+00:00'"
        )
        assert client.get("/admin/api/auth/me").status_code == 401


def test_idle_session_is_rejected(admin: AdminEnv) -> None:
    admin.client.app.state.admin_db.execute(  # type: ignore[attr-defined]
        "UPDATE admin_sessions SET last_seen_at = '2000-01-01T00:00:00+00:00'"
    )
    assert admin.client.get("/admin/api/auth/me").status_code == 401


def test_login_validates_the_body_with_the_standard_envelope(admin_env: AdminEnv) -> None:
    response = admin_env.client.post(LOGIN, json={"username": ""})
    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"


def test_bootstrap_needs_both_values() -> None:
    with pytest.raises(ValueError):
        admin_settings(admin_bootstrap_password=None)


@pytest.fixture
def no_bootstrap_client() -> Iterator[TestClient]:
    app = create_app(admin_settings(admin_bootstrap_user=None, admin_bootstrap_password=None))
    with TestClient(app) as client:
        yield client


def test_without_bootstrap_there_is_no_default_account(no_bootstrap_client: TestClient) -> None:
    for username, password in (("admin", "admin"), ("admin", "changeme123456"), ("root", "")):
        response = no_bootstrap_client.post(
            LOGIN, json={"username": username, "password": password}
        )
        assert response.status_code in (401, 422)
