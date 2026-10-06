from tests.admin_api.conftest import AdminEnv
from tests.admin_api.world import (
    Fakes,
    forward_definition,
    job_body,
    make_job,
    reverse_definition,
    save_mapping,
    wait_for_run,
)

JOBS = "/admin/api/jobs"
RUNS = "/admin/api/runs"


def test_job_crud_roundtrip_and_scheduler_refresh(admin: AdminEnv) -> None:
    fakes = Fakes(admin)
    refreshed: list[str] = []

    async def spy() -> None:
        refreshed.append("refresh")

    admin.client.app.state.admin.scheduler.refresh = spy  # type: ignore[attr-defined]
    save_mapping(admin, forward_definition())
    created = admin.post(
        JOBS, json=job_body(fakes, trigger={"kind": "schedule", "cron": "*/5 * * * *"})
    )
    assert created.status_code == 201, created.text
    job = created.json()
    assert job["trigger"] == {"kind": "schedule", "cron": "*/5 * * * *"} and job["enabled"] is True
    changed = {**job_body(fakes), "batch_size": 10, "enabled": False}
    updated = admin.put(f"{JOBS}/{job['id']}", json=changed)
    assert updated.status_code == 200 and updated.json()["batch_size"] == 10
    assert admin.get(f"{JOBS}/{job['id']}").json()["enabled"] is False
    assert [j["name"] for j in admin.get(JOBS).json()["items"]] == ["customers-sync"]
    assert admin.delete(f"{JOBS}/{job['id']}").status_code == 204
    assert refreshed == ["refresh"] * 3  # create, update, delete


def test_job_validation_and_conflicts(admin: AdminEnv) -> None:
    fakes = Fakes(admin)
    save_mapping(admin, forward_definition())
    assert admin.post(JOBS, json=job_body(fakes)).status_code == 201
    assert admin.post(JOBS, json=job_body(fakes)).status_code == 409  # name taken
    bad_cron = admin.post(
        JOBS, json=job_body(fakes, name="b", trigger={"kind": "schedule", "cron": "nope"})
    )
    assert bad_cron.status_code == 422 and bad_cron.json()["error"] == "validation_error"
    no_reverse = admin.post(JOBS, json=job_body(fakes, name="c", direction="bidirectional"))
    assert no_reverse.status_code == 422
    missing_mapping = admin.post(JOBS, json=job_body(fakes, name="d", mapping={"name": "ghost"}))
    assert missing_mapping.status_code == 404
    missing_profile = admin.post(
        JOBS, json=job_body(fakes, name="e", source={"profile_id": 999, "resource": "customers"})
    )
    assert missing_profile.status_code == 404
    unknown_field = admin.post(JOBS, json=job_body(fakes, name="f", surprise=True))
    assert unknown_field.status_code == 422


def test_job_mapping_must_map_the_jobs_resources(admin: AdminEnv) -> None:
    fakes = Fakes(admin)
    save_mapping(admin, forward_definition())
    wrong = admin.post(
        JOBS, json=job_body(fakes, target={"profile_id": fakes.dst_id, "resource": "other"})
    )
    assert wrong.status_code == 422 and "maps" in wrong.json()["detail"]
    save_mapping(admin, reverse_definition())
    reverse_ok = admin.post(
        JOBS,
        json=job_body(fakes, name="bi", direction="bidirectional", reverse_mapping={"name": "rev"}),
    )
    assert reverse_ok.status_code == 201, reverse_ok.text
    reverse_wrong = admin.post(
        JOBS,
        json=job_body(
            fakes, name="bi2", direction="bidirectional", reverse_mapping={"name": "fwd"}
        ),
    )
    assert reverse_wrong.status_code == 422


def test_mapping_in_use_cannot_be_deleted(admin: AdminEnv) -> None:
    fakes = Fakes(admin)
    make_job(admin, fakes)
    assert admin.delete("/admin/api/mappings/fwd").status_code == 409


def test_manual_trigger_returns_the_run_id_and_finishes_in_the_background(admin: AdminEnv) -> None:
    fakes = Fakes(admin)
    fakes.seed(3)
    job_id = make_job(admin, fakes)
    response = admin.post(f"{JOBS}/{job_id}/runs", json={})
    assert response.status_code == 202, response.text
    run = response.json()
    assert run["job_id"] == job_id and run["trigger"] == "manual"
    done = wait_for_run(admin, run["id"])
    assert done["status"] == "succeeded" and done["counters"]["created"] == 3
    assert len(fakes.dst.records["clients"]) == 3
    runs = admin.get(f"{RUNS}?job_id={job_id}").json()["items"]
    assert [r["id"] for r in runs] == [run["id"]]
    detail = admin.get(f"{RUNS}/{run['id']}").json()
    assert detail["error_count"] == 0 and detail["options"] == {}


def test_trigger_dry_run_and_refusals(admin: AdminEnv) -> None:
    fakes = Fakes(admin)
    fakes.seed(2)
    job_id = make_job(admin, fakes)
    dry = admin.post(f"{JOBS}/{job_id}/runs", json={"dry_run": True}).json()
    done = wait_for_run(admin, dry["id"])
    assert done["dry_run"] is True and not fakes.dst.records["clients"]
    assert len(admin.get(f"{RUNS}/{dry['id']}").json()["sample"]) == 2
    assert admin.post(f"{JOBS}/999/runs", json={}).status_code == 404


def test_run_errors_listing_retry_failed_and_pagination(admin: AdminEnv) -> None:
    from conector_odoo.domain.errors import RecordRejected

    fakes = Fakes(admin)
    fakes.seed(3)
    fakes.dst.reject_when(
        lambda op, resource, fields: (
            RecordRejected("nope") if fields.get("full_name") == "Ana 2" else None
        )
    )
    job_id = make_job(admin, fakes)
    run = admin.post(f"{JOBS}/{job_id}/runs", json={}).json()
    done = wait_for_run(admin, run["id"])
    assert done["status"] == "partial" and done["counters"]["failed"] == 1
    errors = admin.get(f"{RUNS}/{run['id']}/errors").json()
    assert errors["total"] == 1 and errors["items"][0]["kind"] == "rejected"
    assert errors["items"][0]["record_ref"] == "2"
    assert admin.get(f"{RUNS}/{run['id']}/errors?limit=1&offset=1").json()["items"] == []
    fakes.dst._hooks.clear()  # the remote is fixed now
    retry = admin.post(f"{RUNS}/{run['id']}/retry-failed")
    assert retry.status_code == 202 and retry.json()["parent_run_id"] == run["id"]
    retried = wait_for_run(admin, retry.json()["id"])
    assert retried["status"] == "succeeded" and len(fakes.dst.records["clients"]) == 3
    assert admin.get(f"{RUNS}/{run['id']}/errors?only_unretried=true").json()["items"] == []


def test_cancel_resume_and_run_not_found(admin: AdminEnv) -> None:
    fakes = Fakes(admin)
    fakes.seed(1)
    job_id = make_job(admin, fakes)
    run = admin.post(f"{JOBS}/{job_id}/runs", json={}).json()
    wait_for_run(admin, run["id"])
    assert admin.post(f"{RUNS}/{run['id']}/cancel").status_code == 409  # finished: not active
    assert admin.post(f"{RUNS}/{run['id']}/resume").status_code == 409  # finished: not resumable
    assert admin.post(f"{RUNS}/{run['id']}/retry-failed").status_code == 409
    for path in ("", "/errors"):
        assert admin.get(f"{RUNS}/999{path}").status_code == 404
    for action in ("cancel", "resume", "retry-failed"):
        assert admin.post(f"{RUNS}/999/{action}").status_code == 404


def test_cancel_flags_an_active_run(admin: AdminEnv) -> None:
    fakes = Fakes(admin)
    job_id = make_job(admin, fakes)
    # A run that is registered but never executed stays active: cancel must flag it.
    runner = admin.client.app.state.admin.runner  # type: ignore[attr-defined]
    run = admin.client.portal.call(runner.start, job_id)  # type: ignore[union-attr]
    response = admin.post(f"{RUNS}/{run.id}/cancel")
    assert response.status_code == 200 and response.json()["cancel_requested"] is True


def test_runs_filters(admin: AdminEnv) -> None:
    fakes = Fakes(admin)
    fakes.seed(1)
    job_id = make_job(admin, fakes)
    run = admin.post(f"{JOBS}/{job_id}/runs", json={}).json()
    wait_for_run(admin, run["id"])
    assert len(admin.get(f"{RUNS}?status=succeeded").json()["items"]) == 1
    assert admin.get(f"{RUNS}?status=failed").json()["items"] == []
    assert admin.get(f"{RUNS}?job_id=999").json()["items"] == []
    assert admin.get(f"{RUNS}?status=bogus").status_code == 422
    assert admin.get(f"{RUNS}?limit=0").status_code == 422


def test_dashboard_summarises_the_system(admin: AdminEnv) -> None:
    fakes = Fakes(admin)
    fakes.seed(1)
    job_id = make_job(admin, fakes, trigger={"kind": "schedule", "cron": "0 3 * * *"})
    run = admin.post(f"{JOBS}/{job_id}/runs", json={}).json()
    wait_for_run(admin, run["id"])
    summary = admin.get("/admin/api/dashboard").json()
    assert (summary["profiles"], summary["mappings"]) == (2, 1)
    assert (summary["jobs_total"], summary["jobs_enabled"]) == (1, 1)
    assert summary["runs_last_24h"]["succeeded"] == 1 and summary["active_runs"] == []
    assert [r["id"] for r in summary["recent_runs"]] == [run["id"]]
    assert summary["scheduled"][0]["cron"] == "0 3 * * *"
