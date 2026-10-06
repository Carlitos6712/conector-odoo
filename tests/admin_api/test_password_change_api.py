"""``POST /admin/api/auth/password``: self-service password change for every role."""

from fastapi.testclient import TestClient

from tests.admin_api.conftest import (
    ADMIN_PASSWORD,
    ADMIN_USER,
    OPERATOR_PASSWORD,
    OPERATOR_USER,
    AdminEnv,
)

URL = "/admin/api/auth/password"
LOGIN = "/admin/api/auth/login"
NEW_PASSWORD = "brand-new-password-456"


def _body(current: str, new: str = NEW_PASSWORD) -> dict[str, str]:
    return {"current_password": current, "new_password": new}


def _can_login(env: AdminEnv, username: str, password: str) -> bool:
    other = TestClient(env.client.app)
    return other.post(LOGIN, json={"username": username, "password": password}).status_code == 200


def test_operator_can_change_their_own_password(operator: AdminEnv) -> None:
    response = operator.post(URL, json=_body(OPERATOR_PASSWORD))
    assert response.status_code == 200, response.text
    assert response.json()["user"]["username"] == OPERATOR_USER
    assert _can_login(operator, OPERATOR_USER, NEW_PASSWORD)
    assert not _can_login(operator, OPERATOR_USER, OPERATOR_PASSWORD)


def test_admin_can_change_their_own_password(admin: AdminEnv) -> None:
    assert admin.post(URL, json=_body(ADMIN_PASSWORD)).status_code == 200
    assert _can_login(admin, ADMIN_USER, NEW_PASSWORD)
    assert not _can_login(admin, ADMIN_USER, ADMIN_PASSWORD)


def test_operator_stays_read_only_elsewhere(operator: AdminEnv) -> None:
    assert operator.post(URL, json=_body(OPERATOR_PASSWORD)).status_code == 200
    assert operator.post("/admin/api/users", json={}).status_code == 403


def test_wrong_current_password_is_rejected_and_nothing_changes(operator: AdminEnv) -> None:
    cookie = operator.client.cookies.get("admin_session")
    response = operator.post(URL, json=_body("not-the-current-password"))
    assert response.status_code == 422
    assert response.json()["error"] == "invalid_current_password"
    assert "set-cookie" not in response.headers
    assert operator.client.cookies.get("admin_session") == cookie
    assert operator.client.get("/admin/api/auth/me").status_code == 200
    assert _can_login(operator, OPERATOR_USER, OPERATOR_PASSWORD)


def test_new_password_must_satisfy_the_policy(admin: AdminEnv) -> None:
    response = admin.post(URL, json=_body(ADMIN_PASSWORD, "short"))
    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"
    assert _can_login(admin, ADMIN_USER, ADMIN_PASSWORD)


def test_new_password_must_differ_from_the_current_one(admin: AdminEnv) -> None:
    response = admin.post(URL, json=_body(ADMIN_PASSWORD, ADMIN_PASSWORD))
    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"


def test_requires_a_session_and_a_csrf_token(admin: AdminEnv) -> None:
    anonymous = TestClient(admin.client.app).post(URL, json=_body(ADMIN_PASSWORD))
    assert anonymous.status_code == 401
    missing = admin.client.post(URL, json=_body(ADMIN_PASSWORD))
    wrong = admin.client.post(
        URL, json=_body(ADMIN_PASSWORD), headers={"X-CSRF-Token": "wrong-token"}
    )
    for response in (missing, wrong):
        assert response.status_code == 403
        assert response.json()["error"] == "csrf_invalid"
    assert _can_login(admin, ADMIN_USER, ADMIN_PASSWORD)


def test_rejects_unknown_fields_and_empty_values(admin: AdminEnv) -> None:
    extra = admin.post(URL, json={**_body(ADMIN_PASSWORD), "username": "someone-else"})
    empty = admin.post(URL, json=_body("", NEW_PASSWORD))
    assert extra.status_code == 422 and empty.status_code == 422


def test_other_sessions_are_revoked(admin: AdminEnv) -> None:
    second = TestClient(admin.client.app)
    assert (
        second.post(LOGIN, json={"username": ADMIN_USER, "password": ADMIN_PASSWORD}).status_code
        == 200
    )
    assert second.get("/admin/api/auth/me").status_code == 200
    assert admin.post(URL, json=_body(ADMIN_PASSWORD)).status_code == 200
    assert second.get("/admin/api/auth/me").status_code == 401


def test_current_session_and_csrf_token_are_rotated(admin: AdminEnv) -> None:
    old_cookie = admin.client.cookies.get("admin_session")
    old_csrf = admin.csrf
    response = admin.post(URL, json=_body(ADMIN_PASSWORD))
    assert response.status_code == 200
    body = response.json()
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "path=/admin/api" in cookie and "samesite=lax" in cookie
    assert response.headers["cache-control"] == "no-store"
    new_cookie = admin.client.cookies.get("admin_session")
    assert new_cookie and new_cookie != old_cookie
    assert body["csrf_token"] and body["csrf_token"] != old_csrf and body["expires_at"]
    assert admin.client.get("/admin/api/auth/me").json()["csrf_token"] == body["csrf_token"]
    # The old cookie is worthless and the old CSRF token no longer authorises a change.
    admin.client.cookies.set("admin_session", old_cookie, path="/admin/api")
    assert admin.client.get("/admin/api/auth/me").status_code == 401
    admin.client.cookies.set("admin_session", new_cookie, path="/admin/api")
    stale = admin.client.post(
        URL,
        json=_body(NEW_PASSWORD, "another-new-password-789"),
        headers={"X-CSRF-Token": old_csrf},
    )
    assert stale.status_code == 403
    admin.csrf = body["csrf_token"]
    assert admin.post(URL, json=_body(NEW_PASSWORD, "another-new-password-789")).status_code == 200


def test_wrong_attempts_lock_out_like_login(admin: AdminEnv) -> None:
    for _ in range(5):
        assert admin.post(URL, json=_body("wrong-current-password")).status_code == 422
    locked = admin.post(URL, json=_body(ADMIN_PASSWORD))
    assert locked.status_code == 429
    assert locked.json()["error"] == "too_many_attempts"
    assert int(locked.headers["retry-after"]) > 0
    assert _can_login(admin, ADMIN_USER, ADMIN_PASSWORD) is False  # same per-username lockout


def test_a_successful_change_clears_earlier_failures(admin: AdminEnv) -> None:
    for _ in range(4):
        admin.post(URL, json=_body("wrong-current-password"))
    first = admin.post(URL, json=_body(ADMIN_PASSWORD))
    assert first.status_code == 200
    admin.csrf = first.json()["csrf_token"]  # the session was rotated
    for _ in range(4):
        admin.post(URL, json=_body("wrong-current-password"))
    assert admin.post(URL, json=_body(NEW_PASSWORD, "yet-another-password-1")).status_code == 200


def test_responses_never_carry_passwords_or_hashes(admin: AdminEnv) -> None:
    ok = admin.post(URL, json=_body(ADMIN_PASSWORD))
    bad = admin.post(URL, json=_body("wrong-current-password", "short"))
    for response in (ok, bad):
        for value in (ADMIN_PASSWORD, NEW_PASSWORD, "wrong-current-password", "short"):
            assert value not in response.text
        assert "argon2" not in response.text and "password_hash" not in response.text
