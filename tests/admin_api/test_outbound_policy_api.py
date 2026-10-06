"""The admin API refuses outbound requests to forbidden destinations with a typed 422."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from conector_odoo.main import create_app
from tests.admin_api.conftest import ADMIN_PASSWORD, ADMIN_USER, AdminEnv, admin_settings
from tests.admin_api.test_profiles_api import PROFILES, rest_body

METADATA = "http://169.254.169.254"


def test_openapi_import_from_a_metadata_url_is_a_typed_422(admin: AdminEnv) -> None:
    pid = admin.post(PROFILES, json=rest_body()).json()["id"]
    response = admin.post(
        f"{PROFILES}/{pid}/resources/import", json={"url": f"{METADATA}/openapi.json"}
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "outbound_url_blocked"
    assert "169.254" not in body["detail"] and "URL policy" in body["detail"]


def test_resource_preview_against_a_metadata_profile_is_a_typed_422(admin: AdminEnv) -> None:
    pid = admin.post(PROFILES, json=rest_body(base_url=METADATA)).json()["id"]
    admin.put(
        f"{PROFILES}/{pid}/resources/things",
        json={
            "name": "things",
            "label": "Things",
            "list_endpoint": {"method": "GET", "path": "/things"},
            "items_path": "items",
            "pagination": {"strategy": "none"},
        },
    )
    response = admin.post(f"{PROFILES}/{pid}/resources/things/preview", json={"limit": 1})
    assert response.status_code == 422, response.text
    assert response.json()["error"] == "outbound_url_blocked"


def test_connection_test_of_a_metadata_profile_reports_a_failed_step(admin: AdminEnv) -> None:
    response = admin.post(f"{PROFILES}/test", json=rest_body(base_url=METADATA))
    assert response.status_code == 200
    steps = response.json()["steps"]
    assert steps[-1]["ok"] is False and "URL policy" in steps[-1]["detail"]
    assert "169.254" not in steps[-1]["detail"]


@pytest.fixture
def strict_env() -> Iterator[AdminEnv]:
    app = create_app(admin_settings(outbound_url_policy="strict"))
    with TestClient(app) as client:
        env = AdminEnv(client)
        env.login(ADMIN_USER, ADMIN_PASSWORD)
        yield env


def test_strict_mode_blocks_a_loopback_profile(strict_env: AdminEnv) -> None:
    response = strict_env.post(PROFILES + "/test", json=rest_body(base_url="http://127.0.0.1:9"))
    assert response.status_code == 200
    assert response.json()["steps"][-1]["ok"] is False
    assert "URL policy" in response.json()["steps"][-1]["detail"]
