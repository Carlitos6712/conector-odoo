"""Shared setup for the mapping/job/run API tests: two REST profiles backed by in-memory fakes."""

import time
from typing import Any

from conector_odoo.domain.records import FieldSpec, FieldType, ResourceSchema
from tests.admin_api.conftest import AdminEnv
from tests.unit.fakes_records import InMemoryRecordEndpoint

PROFILES = "/admin/api/profiles"


def schema(name: str, *fields: str) -> ResourceSchema:
    return ResourceSchema(name, name, tuple(FieldSpec(f, FieldType.STRING) for f in fields))


class Fakes:
    def __init__(self, admin: AdminEnv) -> None:
        self.src = InMemoryRecordEndpoint({"customers": schema("customers", "name", "email")})
        self.dst = InMemoryRecordEndpoint({"clients": schema("clients", "full_name", "email")})
        by_name = {"src": self.src, "dst": self.dst}
        admin.client.app.state.admin.endpoints.build_rest = (  # type: ignore[attr-defined]
            lambda profile, secrets, configs: by_name[profile.name]
        )
        self.src_id = self._profile(admin, "src")
        self.dst_id = self._profile(admin, "dst")

    @staticmethod
    def _profile(admin: AdminEnv, name: str) -> int:
        body = {
            "name": name,
            "type": "rest",
            "base_url": "https://api.test",
            "auth_method": "bearer",
            "secrets": {"token": f"token-for-{name}-0123"},
        }
        response = admin.post(PROFILES, json=body)
        assert response.status_code == 201, response.text
        return int(response.json()["id"])

    def seed(self, count: int = 2) -> None:
        for i in range(1, count + 1):
            self.src.seed("customers", {"name": f"Ana {i}", "email": f"ana{i}@x.com"})


def forward_definition(name: str = "fwd") -> dict[str, Any]:
    return {
        "schema_version": 1,
        "name": name,
        "source_resource": "customers",
        "target_resource": "clients",
        "rules": [
            {"target": "full_name", "expr": {"type": "direct", "source": "name"}},
            {"target": "email", "expr": {"type": "direct", "source": "email"}},
        ],
    }


def reverse_definition(name: str = "rev") -> dict[str, Any]:
    return {
        "schema_version": 1,
        "name": name,
        "source_resource": "clients",
        "target_resource": "customers",
        "rules": [{"target": "name", "expr": {"type": "direct", "source": "full_name"}}],
    }


def save_mapping(admin: AdminEnv, definition: dict[str, Any]) -> Any:
    return admin.put(f"/admin/api/mappings/{definition['name']}", json={"definition": definition})


def job_body(fakes: Fakes, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": "customers-sync",
        "source": {"profile_id": fakes.src_id, "resource": "customers"},
        "target": {"profile_id": fakes.dst_id, "resource": "clients"},
        "mapping": {"name": "fwd"},
        "trigger": {"kind": "manual"},
    }
    body.update(overrides)
    return body


def make_job(admin: AdminEnv, fakes: Fakes, **overrides: Any) -> int:
    assert save_mapping(admin, forward_definition()).status_code == 200
    response = admin.post("/admin/api/jobs", json=job_body(fakes, **overrides))
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def wait_for_run(admin: AdminEnv, run_id: int, timeout: float = 10.0) -> dict[str, Any]:
    """Poll until the background run is no longer active."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run: dict[str, Any] = admin.client.get(f"/admin/api/runs/{run_id}").json()
        if run["status"] not in ("queued", "running"):
            return run
        time.sleep(0.02)
    raise AssertionError(f"run {run_id} did not finish")
