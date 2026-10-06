from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conector_odoo.main import create_app
from tests.admin_api.conftest import AdminEnv, admin_settings

URL = "/admin/api/vault"


@pytest.fixture
def keyless(tmp_path: Path) -> AdminEnv:
    app = create_app(admin_settings(encryption_key=None, admin_db_path=str(tmp_path / "admin.db")))
    with TestClient(app) as client:
        env = AdminEnv(client)
        env.login()
        yield env  # type: ignore[misc]


def test_status_with_env_key(admin: AdminEnv) -> None:
    response = admin.get(f"{URL}/status")
    assert response.status_code == 200
    assert response.json() == {"configured": True, "source": "env"}


def test_generate_conflicts_when_env_key_is_set(admin: AdminEnv) -> None:
    response = admin.post(f"{URL}/generate")
    assert response.status_code == 409
    assert response.json()["error"] == "conflict"


def test_generate_then_vault_works_without_restart(keyless: AdminEnv) -> None:
    assert keyless.get(f"{URL}/status").json() == {"configured": False, "source": None}
    created = keyless.post(f"{URL}/generate")
    assert created.status_code == 201
    assert created.json() == {"configured": True, "source": "file"}
    assert keyless.get(f"{URL}/status").json() == {"configured": True, "source": "file"}
    assert keyless.post(f"{URL}/generate").status_code == 409
    profile = keyless.post(
        "/admin/api/profiles",
        json={
            "name": "r",
            "type": "rest",
            "base_url": "https://api.test",
            "auth_method": "bearer",
            "secrets": {"token": "a-bearer-token"},
        },
    )
    assert profile.status_code == 201, profile.text


def test_responses_never_carry_key_material(keyless: AdminEnv, tmp_path: Path) -> None:
    created = keyless.post(f"{URL}/generate")
    key = (tmp_path / "vault.key").read_text().strip()
    assert key and key not in created.text
    assert key not in keyless.get(f"{URL}/status").text
