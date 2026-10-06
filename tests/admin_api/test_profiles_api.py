from typing import Any

import pytest

from conector_odoo.domain.profiles import ConnectionProfile, ProbeStep, ProfileType, Secrets
from tests.admin_api.conftest import AdminEnv, admin_settings

TOKEN = "tok-SECRET-0123456789"
CLIENT_SECRET = "client-SECRET-abcdef"

PROFILES = "/admin/api/profiles"


def rest_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": "suwe",
        "type": "rest",
        "base_url": "https://api.test",
        "auth_method": "bearer",
        "secrets": {"token": TOKEN},
    }
    body.update(overrides)
    return body


def test_create_get_list_never_return_secrets(admin: AdminEnv) -> None:
    created = admin.post(
        PROFILES, json=rest_body(secrets={"token": TOKEN, "client_secret": CLIENT_SECRET})
    )
    assert created.status_code == 201, created.text
    profile = created.json()
    assert profile["has_secret"]["token"] is True and profile["has_secret"]["client_secret"] is True
    assert profile["has_secret"]["api_key"] is False
    responses = [
        created,
        admin.get(f"{PROFILES}/{profile['id']}"),
        admin.get(PROFILES),
        admin.put(f"{PROFILES}/{profile['id']}", json=rest_body(timeout_seconds=12)),
    ]
    for response in responses:
        assert response.status_code in (200, 201)
        assert TOKEN not in response.text and CLIENT_SECRET not in response.text
        assert "secrets" not in response.json() or response.json().get("items") is not None


def test_secrets_are_encrypted_at_rest(admin: AdminEnv) -> None:
    admin.post(PROFILES, json=rest_body())
    blob = admin.client.app.state.admin_db.execute(  # type: ignore[attr-defined]
        "SELECT secrets_blob FROM connection_profiles"
    ).fetchone()[0]
    assert TOKEN.encode() not in blob


def test_update_keeps_omitted_secrets_and_clears_with_empty_string(admin: AdminEnv) -> None:
    pid = admin.post(PROFILES, json=rest_body()).json()["id"]
    kept = admin.put(f"{PROFILES}/{pid}", json=rest_body(secrets=None, timeout_seconds=5)).json()
    assert kept["has_secret"]["token"] is True and kept["timeout_seconds"] == 5
    cleared = admin.put(f"{PROFILES}/{pid}", json=rest_body(secrets={"token": ""})).json()
    assert cleared["has_secret"]["token"] is False


def test_error_envelope_for_conflicts_validation_and_missing(admin: AdminEnv) -> None:
    assert admin.post(PROFILES, json=rest_body()).status_code == 201
    duplicate = admin.post(PROFILES, json=rest_body())
    assert duplicate.status_code == 409 and duplicate.json()["error"] == "conflict"
    invalid = admin.post(PROFILES, json=rest_body(name="x", timeout_seconds=0))
    assert invalid.status_code == 422 and invalid.json()["error"] == "validation_error"
    unknown = admin.post(PROFILES, json=rest_body(name="y", surprise=1))
    assert unknown.status_code == 422
    assert admin.get(f"{PROFILES}/999").status_code == 404
    assert admin.delete(f"{PROFILES}/999").json()["error"] == "not_found"


def test_delete_profile_and_refuse_when_in_use(admin: AdminEnv) -> None:
    pid = admin.post(PROFILES, json=rest_body()).json()["id"]
    resource = {
        "name": "items",
        "label": "Items",
        "list_endpoint": {"method": "GET", "path": "/items"},
    }
    assert admin.put(f"{PROFILES}/{pid}/resources/items", json=resource).status_code == 200
    in_use = admin.delete(f"{PROFILES}/{pid}")
    assert in_use.status_code == 409
    admin.delete(f"{PROFILES}/{pid}/resources/items")
    assert admin.delete(f"{PROFILES}/{pid}").status_code == 204


def test_creating_secrets_without_a_vault_key_is_a_clean_503() -> None:
    from fastapi.testclient import TestClient

    from conector_odoo.main import create_app
    from tests.admin_api.conftest import AdminEnv as Env

    with TestClient(create_app(admin_settings(encryption_key=None))) as client:
        env = Env(client)
        env.login()
        response = env.post(PROFILES, json=rest_body())
        assert response.status_code == 503
        assert response.json()["error"] == "vault_not_configured"
        assert TOKEN not in response.text


class LeakyProbe:
    """A probe whose messages echo the secret: the API must mask it anyway."""

    def __init__(self) -> None:
        self.seen: list[tuple[ConnectionProfile, Secrets]] = []

    async def probe(self, profile: ConnectionProfile, secrets: Secrets) -> list[ProbeStep]:
        self.seen.append((profile, secrets))
        return [
            ProbeStep("url_valid", True, "ok"),
            ProbeStep("auth", False, f"server said token {secrets.token} is wrong", "check it"),
        ]


def test_test_connection_for_saved_and_draft_profiles_masks_secrets(admin: AdminEnv) -> None:
    probe = LeakyProbe()
    admin.client.app.state.admin.profiles.probes[ProfileType.REST] = probe  # type: ignore[attr-defined]
    pid = admin.post(PROFILES, json=rest_body()).json()["id"]
    saved = admin.post(f"{PROFILES}/{pid}/test")
    assert saved.status_code == 200
    assert saved.json()["ok"] is False and saved.json()["failed_step"] == "auth"
    assert saved.json()["steps"][1]["hint"] == "check it"
    assert probe.seen[-1][1].token == TOKEN  # the stored secret reached the probe...
    assert TOKEN not in saved.text  # ...but never the response
    draft = admin.post(f"{PROFILES}/test", json=rest_body(name="draft"))
    assert draft.status_code == 200 and TOKEN not in draft.text
    assert admin.get(PROFILES).json()["items"][0]["name"] == "suwe"  # a draft test saves nothing
    assert len(admin.get(PROFILES).json()["items"]) == 1


def test_test_connection_of_missing_profile_is_404(admin: AdminEnv) -> None:
    assert admin.post(f"{PROFILES}/999/test").status_code == 404


@pytest.mark.parametrize("field", ["api_key", "token", "client_id", "client_secret", "password"])
def test_every_secret_field_is_write_only(admin: AdminEnv, field: str) -> None:
    value = f"VALUE-{field}-0123456789"
    response = admin.post(PROFILES, json=rest_body(secrets={field: value}))
    assert response.status_code == 201
    assert value not in response.text and value not in admin.get(PROFILES).text


def test_username_is_stored_and_returned_but_the_password_is_not(admin: AdminEnv) -> None:
    body = rest_body(
        auth_method="oauth2_client_credentials",
        token_url="https://idp.test/token",
        username="alice",
        secrets={"client_id": "cid", "password": "app-PASSWORD-xyz"},
    )
    created = admin.post(PROFILES, json=body)
    assert created.status_code == 201, created.text
    profile = created.json()
    assert profile["username"] == "alice"
    assert profile["has_secret"]["password"] is True
    assert "app-PASSWORD-xyz" not in created.text
    fetched = admin.get(f"{PROFILES}/{profile['id']}")
    assert fetched.json()["username"] == "alice"
