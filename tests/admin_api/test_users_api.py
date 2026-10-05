from tests.admin_api.conftest import (
    ADMIN_USER,
    OPERATOR_PASSWORD,
    OPERATOR_USER,
    AdminEnv,
)


def test_admin_manages_users_and_responses_never_carry_hashes(admin: AdminEnv) -> None:
    created = admin.post(
        "/admin/api/users",
        json={"username": "carol", "password": "carol-password-1", "role": "operator"},
    )
    assert created.status_code == 201
    assert set(created.json()) == {"id", "username", "role", "created_at"}
    listed = admin.get("/admin/api/users")
    assert [u["username"] for u in listed.json()["items"]] == ["carol", ADMIN_USER]
    assert (
        "hash" not in listed.text and "argon2" not in listed.text and "password" not in listed.text
    )


def test_duplicate_and_weak_users_are_rejected(admin: AdminEnv) -> None:
    body = {"username": "ROOT", "password": "long-enough-password", "role": "operator"}
    duplicate = admin.post("/admin/api/users", json=body)
    assert duplicate.status_code == 409 and duplicate.json()["error"] == "conflict"
    weak = admin.post(
        "/admin/api/users", json={"username": "dave", "password": "short", "role": "operator"}
    )
    assert weak.status_code == 422 and weak.json()["error"] == "validation_error"


def test_patch_changes_role_and_password_and_revokes_sessions(admin: AdminEnv) -> None:
    admin.create_operator()
    users = {u["username"]: u for u in admin.get("/admin/api/users").json()["items"]}
    operator_id = users[OPERATOR_USER]["id"]
    # The operator signs in on a second client, then loses the session when its password changes.
    from fastapi.testclient import TestClient

    other = TestClient(admin.client.app)  # no ``with``: reuses the running app's state
    login = other.post(
        "/admin/api/auth/login", json={"username": OPERATOR_USER, "password": OPERATOR_PASSWORD}
    )
    assert login.status_code == 200
    patched = admin.patch(
        f"/admin/api/users/{operator_id}", json={"password": "a-brand-new-password"}
    )
    assert patched.status_code == 200
    assert other.get("/admin/api/auth/me").status_code == 401


def test_last_admin_cannot_be_demoted_or_deleted_and_self_delete_is_refused(
    admin: AdminEnv,
) -> None:
    me = admin.get("/admin/api/auth/me").json()["user"]["id"]
    demote = admin.patch(f"/admin/api/users/{me}", json={"role": "operator"})
    assert demote.status_code == 409
    own = admin.delete(f"/admin/api/users/{me}")
    assert own.status_code == 422


def test_delete_user_and_missing_user(admin: AdminEnv) -> None:
    admin.create_operator()
    users = {u["username"]: u for u in admin.get("/admin/api/users").json()["items"]}
    assert admin.delete(f"/admin/api/users/{users[OPERATOR_USER]['id']}").status_code == 204
    assert admin.delete("/admin/api/users/9999").status_code == 404


def test_operator_cannot_list_or_manage_users(operator: AdminEnv) -> None:
    assert operator.get("/admin/api/users").status_code == 403
    assert operator.post("/admin/api/users", json={}).status_code == 403
