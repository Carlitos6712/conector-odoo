import json
import sqlite3
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from conector_odoo.application.scheduler import SyncScheduler
from conector_odoo.infrastructure.endpoints import ProfileEndpoints
from conector_odoo.main import create_app
from tests.admin_api.conftest import AdminEnv, admin_settings
from tests.admin_api.world import Fakes, forward_definition, job_body, save_mapping
from tests.api.test_webhooks import SECRET, payload, signed_headers


def test_verified_webhook_event_runs_the_matching_job(admin: AdminEnv) -> None:
    fakes = Fakes(admin)
    fakes.seed(2)
    save_mapping(admin, forward_definition())
    trigger = {"kind": "webhook", "event_types": ["partner.created"]}
    created = admin.post("/admin/api/jobs", json=job_body(fakes, trigger=trigger))
    assert created.status_code == 201, created.text
    body = payload(model="res.partner")
    raw = json.dumps(body).encode()
    response = admin.client.post("/webhooks/odoo", content=raw, headers=signed_headers(raw))
    assert response.status_code == 202
    deadline = time.monotonic() + 10
    runs: list[dict[str, Any]] = []
    while time.monotonic() < deadline and not (
        runs := admin.client.get("/admin/api/runs").json()["items"]
    ):
        time.sleep(0.02)
    assert runs and runs[0]["trigger"] == "webhook"
    while time.monotonic() < deadline and len(fakes.dst.records["clients"]) < 2:
        time.sleep(0.02)
    assert len(fakes.dst.records["clients"]) == 2
    assert SECRET  # the webhook route keeps its own HMAC authentication, no session needed


def test_scheduler_starts_and_stops_with_the_app(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    real_start, real_stop = SyncScheduler.start, SyncScheduler.stop

    def start(self: SyncScheduler) -> None:
        calls.append("start")
        real_start(self)

    async def stop(self: SyncScheduler) -> None:
        calls.append("stop")
        await real_stop(self)

    monkeypatch.setattr(SyncScheduler, "start", start)
    monkeypatch.setattr(SyncScheduler, "stop", stop)
    with TestClient(create_app(admin_settings(sync_scheduler_enabled=True))):
        assert calls == ["start"]
    assert calls == ["start", "stop"]


def test_scheduler_stays_off_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(SyncScheduler, "start", lambda self: calls.append("start"))
    with TestClient(create_app(admin_settings(sync_scheduler_enabled=False))):
        pass
    assert calls == []


def test_shutdown_closes_endpoints_and_cancels_background_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed: list[str] = []
    real_close = ProfileEndpoints.aclose

    async def aclose(self: ProfileEndpoints) -> None:
        closed.append("endpoints")
        await real_close(self)

    monkeypatch.setattr(ProfileEndpoints, "aclose", aclose)
    app = create_app(admin_settings())
    with TestClient(app):
        pass
    assert closed == ["endpoints"]
    assert app.state.admin.launcher.active == 0


def test_a_failing_startup_step_releases_every_resource(tmp_path: Any) -> None:
    # A bootstrap password shorter than the policy fails AFTER the admin database was opened.
    settings = admin_settings(
        admin_bootstrap_password="short", idempotency_db_path=str(tmp_path / "idem.db")
    )
    app = create_app(settings)
    with pytest.raises(Exception, match="password must be at least"), TestClient(app):
        pass
    with pytest.raises(sqlite3.ProgrammingError):  # the admin connection was closed
        app.state.admin_db.execute("SELECT 1")
    with pytest.raises(sqlite3.ProgrammingError):  # and so were the container's stores
        app.state.container.idempotency._conn.execute("SELECT 1")
