"""``/admin/api/odoo/active`` and the active markers on ``/admin/api/profiles``."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from conector_odoo.domain.profiles import ConnectionProfile, ProbeStep, ProfileType, Secrets
from conector_odoo.main import create_app
from tests.admin_api.conftest import AdminEnv, admin_settings

API_KEY = "profile-odoo-api-key-0123456789"
URL = "/admin/api/odoo/active"


class FakeProbe:
    def __init__(self) -> None:
        self.ok = True

    async def probe(self, profile: ConnectionProfile, secrets: Secrets) -> list[ProbeStep]:
        if self.ok:
            return [ProbeStep("reachable", True, "ok"), ProbeStep("auth", True, "uid 2")]
        return [
            ProbeStep("reachable", True, "ok"),
            ProbeStep("auth", False, "Odoo rejected the credentials", "Check the API key."),
        ]


def odoo_profile(name: str = "prod", **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": name,
        "type": "odoo",
        "base_url": "https://odoo.example.com",
        "auth_method": "api_key",
        "odoo_db": "proddb",
        "odoo_login": "bot@example.com",
        "secrets": {"api_key": API_KEY},
    }
    body.update(overrides)
    return body


def create(admin: AdminEnv, name: str = "prod", **overrides: Any) -> int:
    response = admin.post("/admin/api/profiles", json=odoo_profile(name, **overrides))
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


@pytest.fixture
def probe(admin: AdminEnv) -> FakeProbe:
    fake = FakeProbe()
    admin.client.app.state.admin.profiles.probes[ProfileType.ODOO] = fake  # type: ignore[attr-defined]
    return fake


@pytest.fixture
def bare_admin() -> Iterator[AdminEnv]:
    settings = admin_settings(odoo_url=None, odoo_db=None, odoo_user=None, odoo_api_key=None)
    with TestClient(create_app(settings)) as client:
        env = AdminEnv(client)
        env.login()
        env.client.app.state.admin.profiles.probes[ProfileType.ODOO] = FakeProbe()  # type: ignore[attr-defined]
        yield env


def test_the_env_connection_is_reported_read_only(admin: AdminEnv) -> None:
    body = admin.get(URL).json()
    assert body["source"] == "env"
    assert body["profile_id"] is None
    assert body["base_url"] == "https://odoo.test"
    assert body["db"] == "db"
    assert body["login"] == "bot"
    assert body["status"] == "active"
    assert "api_key" not in body and "secret" not in str(body).lower()


def test_nothing_configured_is_source_none(bare_admin: AdminEnv) -> None:
    body = bare_admin.get(URL).json()
    assert body["source"] == "none"
    assert body["status"] == "not_configured"
    assert body["profile_id"] is None and body["base_url"] is None


def test_an_operator_may_read_but_not_change_the_connection(operator: AdminEnv) -> None:
    assert operator.get(URL).status_code == 200
    assert operator.put(URL, json={"profile_id": 1}).status_code == 403
    assert operator.delete(URL).status_code == 403


def test_activating_a_profile_makes_it_the_live_connection(
    admin: AdminEnv, probe: FakeProbe
) -> None:
    profile_id = create(admin)
    response = admin.put(URL, json={"profile_id": profile_id})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"] == "profile"
    assert body["profile_id"] == profile_id
    assert body["profile_name"] == "prod"
    assert (body["base_url"], body["db"], body["login"]) == (
        "https://odoo.example.com",
        "proddb",
        "bot@example.com",
    )
    assert body["last_connected_at"] is not None
    assert API_KEY not in response.text
    assert admin.get(URL).json()["profile_id"] == profile_id


def test_the_profile_list_marks_the_active_one(admin: AdminEnv, probe: FakeProbe) -> None:
    first, second = create(admin, "one"), create(admin, "two")
    before = {p["id"]: p for p in admin.get("/admin/api/profiles").json()["items"]}
    assert before[first]["is_active"] is False
    assert before[first]["last_connected_at"] is None
    admin.put(URL, json={"profile_id": second})
    after = {p["id"]: p for p in admin.get("/admin/api/profiles").json()["items"]}
    assert after[second]["is_active"] is True
    assert after[second]["last_connected_at"] is not None
    assert after[first]["is_active"] is False
    assert admin.get(f"/admin/api/profiles/{second}").json()["is_active"] is True


def test_a_failed_probe_answers_422_and_keeps_the_previous_connection(
    admin: AdminEnv, probe: FakeProbe
) -> None:
    profile_id = create(admin)
    probe.ok = False
    response = admin.put(URL, json={"profile_id": profile_id})
    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "odoo_activation_failed"
    assert body["failed_step"] == "auth"
    assert [s["name"] for s in body["steps"]] == ["reachable", "auth"]
    assert API_KEY not in response.text
    current = admin.get(URL).json()
    assert current["source"] == "env"  # the previous connection stayed
    assert admin.get(f"/admin/api/profiles/{profile_id}").json()["is_active"] is False


def test_activating_an_unknown_profile_is_404(admin: AdminEnv, probe: FakeProbe) -> None:
    response = admin.put(URL, json={"profile_id": 999})
    assert response.status_code == 404
    assert response.json()["error"] == "not_found"


def test_only_odoo_profiles_can_be_activated(admin: AdminEnv, probe: FakeProbe) -> None:
    rest = admin.post(
        "/admin/api/profiles",
        json={
            "name": "rest",
            "type": "rest",
            "base_url": "https://api.example.com",
            "auth_method": "api_key",
        },
    ).json()["id"]
    response = admin.put(URL, json={"profile_id": rest})
    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"


def test_the_body_is_validated(admin: AdminEnv) -> None:
    assert admin.put(URL, json={}).status_code == 422
    assert admin.put(URL, json={"profile_id": 1, "extra": 1}).status_code == 422


def test_disconnecting_falls_back_to_env(admin: AdminEnv, probe: FakeProbe) -> None:
    admin.put(URL, json={"profile_id": create(admin)})
    response = admin.delete(URL)
    assert response.status_code == 200
    assert response.json()["source"] == "env"


def test_disconnecting_without_env_leaves_nothing_configured(bare_admin: AdminEnv) -> None:
    profile_id = create(bare_admin)
    assert bare_admin.put(URL, json={"profile_id": profile_id}).status_code == 200
    body = bare_admin.delete(URL).json()
    assert body["source"] == "none"
    assert body["last_connected_at"] is not None  # the last connection is remembered
    assert bare_admin.get("/customers").status_code == 503


def test_the_active_profile_cannot_be_deleted(admin: AdminEnv, probe: FakeProbe) -> None:
    profile_id = create(admin)
    admin.put(URL, json={"profile_id": profile_id})
    response = admin.delete(f"/admin/api/profiles/{profile_id}")
    assert response.status_code == 409
    assert "active" in response.json()["detail"].lower()
    assert admin.delete(URL).status_code == 200
    assert admin.delete(f"/admin/api/profiles/{profile_id}").status_code == 204


def test_editing_the_active_profile_reloads_the_live_connection(
    admin: AdminEnv, probe: FakeProbe
) -> None:
    profile_id = create(admin)
    admin.put(URL, json={"profile_id": profile_id})
    provider = admin.client.app.state.container.odoo  # type: ignore[attr-defined]
    before = provider.current
    response = admin.put(
        f"/admin/api/profiles/{profile_id}", json=odoo_profile(odoo_db="otherdb", secrets=None)
    )
    assert response.status_code == 200, response.text
    assert provider.current is not before
    assert admin.get(URL).json()["db"] == "otherdb"
    assert admin.get(URL).json()["source"] == "profile"


def test_the_active_connection_survives_a_restart(tmp_path: Path) -> None:
    db = str(tmp_path / "admin.db")

    def settings() -> Any:
        return admin_settings(
            admin_db_path=db, odoo_url=None, odoo_db=None, odoo_user=None, odoo_api_key=None
        )

    with TestClient(create_app(settings())) as client:
        first = AdminEnv(client)
        first.login()
        client.app.state.admin.profiles.probes[ProfileType.ODOO] = FakeProbe()  # type: ignore[attr-defined]
        profile_id = create(first)
        assert first.put(URL, json={"profile_id": profile_id}).status_code == 200
    with TestClient(create_app(settings())) as client:
        second = AdminEnv(client)
        second.login()
        body = second.get(URL).json()
        assert body["source"] == "profile"
        assert body["profile_id"] == profile_id
        assert body["last_connected_at"] is not None
