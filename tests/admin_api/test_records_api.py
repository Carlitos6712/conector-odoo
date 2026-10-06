"""``/admin/api/profiles/{id}/records/{resource}``: list, get, edit and delete ONE record."""

from typing import Any

from conector_odoo.domain.records import FieldSpec, FieldType, ResourceSchema
from conector_odoo.infrastructure.odoo.client import OdooClient
from conector_odoo.infrastructure.odoo.records import OdooRecordEndpoint
from tests.adapters.test_odoo_record_endpoint import FakeOdoo, partner
from tests.admin_api.conftest import AdminEnv
from tests.admin_api.test_profiles_api import PROFILES
from tests.admin_api.test_resources_api import make_profile
from tests.admin_api.world import (
    Fakes,
    make_job,
    reverse_definition,
    save_mapping,
    wait_for_run,
)

NOTES = ResourceSchema(
    "notes",
    "Notes",
    (
        FieldSpec("title", FieldType.STRING),
        FieldSpec("body", FieldType.STRING),
        FieldSpec("created", FieldType.DATETIME, readonly=True),
    ),
)


class Notes:
    """One REST profile backed by an in-memory endpoint with three records."""

    def __init__(self, admin: AdminEnv) -> None:
        from tests.unit.fakes_records import InMemoryRecordEndpoint

        self.endpoint = InMemoryRecordEndpoint({"notes": NOTES})
        admin.client.app.state.admin.endpoints.build_rest = (  # type: ignore[attr-defined]
            lambda profile, secrets, configs: self.endpoint
        )
        self.pid = make_profile(admin)
        self.url = f"{PROFILES}/{self.pid}/records/notes"
        for i in (1, 2, 3):
            self.endpoint.seed("notes", {"title": f"Note {i}", "body": f"text {i}", "created": "x"})


def odoo_profile(admin: AdminEnv) -> tuple[int, FakeOdoo]:
    odoo = FakeOdoo()
    odoo.rows["res.partner"] = [partner(i) for i in range(1, 6)]
    admin.client.app.state.admin.endpoints.build_odoo = (  # type: ignore[attr-defined]
        lambda profile, secrets: OdooRecordEndpoint(OdooClient(odoo))
    )
    pid = make_profile(
        admin,
        name="odoo",
        type="odoo",
        base_url="https://odoo.test",
        auth_method="api_key",
        odoo_db="db",
        odoo_login="bot",
        secrets={"api_key": "odoo-key-0123456789"},
    )
    return pid, odoo


# -- list ------------------------------------------------------------------------------------


def test_list_returns_records_schema_and_paging(admin: AdminEnv) -> None:
    notes = Notes(admin)
    body = admin.get(notes.url).json()
    assert [r["fields"]["title"] for r in body["items"]] == ["Note 1", "Note 2", "Note 3"]
    assert (body["limit"], body["offset"], body["has_more"]) == (25, 0, False)
    assert {f["name"] for f in body["schema"]["fields"]} == {"title", "body", "created"}


def test_list_paginates_with_limit_and_offset(admin: AdminEnv) -> None:
    notes = Notes(admin)
    first = admin.get(f"{notes.url}?limit=2").json()
    assert [r["id"] for r in first["items"]] == ["1", "2"] and first["has_more"] is True
    last = admin.get(f"{notes.url}?limit=2&offset=2").json()
    assert [r["id"] for r in last["items"]] == ["3"] and last["has_more"] is False


def test_list_caps_the_page_size_and_rejects_bad_paging(admin: AdminEnv) -> None:
    notes = Notes(admin)
    for query in ("limit=101", "limit=0", "offset=-1", "offset=10001"):
        assert admin.get(f"{notes.url}?{query}").status_code == 422, query


def test_list_search_is_a_case_insensitive_text_match(admin: AdminEnv) -> None:
    notes = Notes(admin)
    body = admin.get(f"{notes.url}?search=NOTE 2").json()
    assert [r["id"] for r in body["items"]] == ["2"]
    assert admin.get(f"{notes.url}?search=zzz").json()["items"] == []


def test_list_of_an_unknown_profile_or_resource_is_404(admin: AdminEnv) -> None:
    notes = Notes(admin)
    assert admin.get(f"{PROFILES}/999/records/notes").status_code == 404
    assert admin.get(f"{PROFILES}/{notes.pid}/records/nope").status_code == 404


def test_odoo_search_uses_name_ilike_and_pages_with_the_domain(admin: AdminEnv) -> None:
    pid, odoo = odoo_profile(admin)
    response = admin.get(f"{PROFILES}/{pid}/records/res.partner?search=P3&limit=1")
    assert response.status_code == 200, response.text
    assert [r["id"] for r in response.json()["items"]] == ["3"]
    domains = [c[2][0] for c in odoo.calls_to("search_read")]
    assert [["name", "ilike", "P3"]] in domains


# -- get -------------------------------------------------------------------------------------


def test_get_one_record_and_404_when_missing(admin: AdminEnv) -> None:
    notes = Notes(admin)
    got = admin.get(f"{notes.url}/2").json()
    assert got["id"] == "2" and got["fields"]["title"] == "Note 2"
    assert admin.get(f"{notes.url}/99").status_code == 404


# -- patch -----------------------------------------------------------------------------------


def test_patch_updates_only_the_given_fields(admin: AdminEnv) -> None:
    notes = Notes(admin)
    response = admin.patch(f"{notes.url}/2", json={"fields": {"title": "Renamed"}})
    assert response.status_code == 200, response.text
    assert response.json()["fields"]["title"] == "Renamed"
    assert response.json()["fields"]["body"] == "text 2"
    assert admin.get(f"{notes.url}/2").json()["fields"]["title"] == "Renamed"


def test_patch_rejects_unknown_readonly_and_empty_changes(admin: AdminEnv) -> None:
    notes = Notes(admin)
    for fields in ({"nope": 1}, {"created": "y"}, {"id": "9"}, {}):
        response = admin.patch(f"{notes.url}/2", json={"fields": fields})
        assert response.status_code == 422, fields
        assert response.json()["error"] == "validation_error"
    assert notes.endpoint.update_calls == 0
    assert admin.patch(f"{notes.url}/2", json={"title": "x"}).status_code == 422  # no wrapper


def test_patch_of_a_missing_record_is_404(admin: AdminEnv) -> None:
    notes = Notes(admin)
    assert admin.patch(f"{notes.url}/99", json={"fields": {"title": "x"}}).status_code == 404


def test_odoo_patch_writes_through_the_adapter(admin: AdminEnv) -> None:
    pid, odoo = odoo_profile(admin)
    response = admin.patch(
        f"{PROFILES}/{pid}/records/res.partner/2", json={"fields": {"name": "Renamed"}}
    )
    assert response.status_code == 200, response.text
    assert odoo.calls_to("write")[0][2] == [[2], {"name": "Renamed"}]
    readonly = admin.patch(
        f"{PROFILES}/{pid}/records/res.partner/2", json={"fields": {"write_date": "x"}}
    )
    assert readonly.status_code == 422


# -- delete ----------------------------------------------------------------------------------


def test_delete_removes_exactly_one_record(admin: AdminEnv) -> None:
    notes = Notes(admin)
    response = admin.delete(f"{notes.url}/2")
    assert response.status_code == 200 and response.json() == {
        "propagation": [],
        "warnings": [],
        "already_deleted": False,
    }
    assert sorted(notes.endpoint.records["notes"]) == ["1", "3"]


def test_delete_of_an_already_gone_record_is_an_idempotent_success(admin: AdminEnv) -> None:
    notes = Notes(admin)
    assert admin.delete(f"{notes.url}/2").status_code == 200
    again = admin.delete(f"{notes.url}/2")
    assert again.status_code == 200, again.text
    assert again.json() == {"propagation": [], "warnings": [], "already_deleted": True}
    assert sorted(notes.endpoint.records["notes"]) == ["1", "3"]


def test_delete_on_an_unknown_profile_or_resource_is_404(admin: AdminEnv) -> None:
    notes = Notes(admin)
    assert admin.delete(f"{PROFILES}/999/records/notes/1").status_code == 404
    assert admin.delete(f"{PROFILES}/{notes.pid}/records/nope/1").status_code == 404


def test_there_is_no_collection_level_or_filter_based_delete(admin: AdminEnv) -> None:
    notes = Notes(admin)
    assert admin.delete(notes.url).status_code in (404, 405)
    assert admin.delete(f"{notes.url}?search=Note").status_code in (404, 405)
    assert len(notes.endpoint.records["notes"]) == 3
    paths = admin.client.app.openapi()["paths"]
    deletes = [p for p, ops in paths.items() if "/records/" in p and "delete" in ops]
    assert deletes and all(p.endswith("/{record_id}") for p in deletes)


def test_odoo_delete_unlinks_and_a_refusal_is_a_422_with_odoo_message(admin: AdminEnv) -> None:
    from conector_odoo.domain.errors import OdooValidationError

    pid, odoo = odoo_profile(admin)
    url = f"{PROFILES}/{pid}/records/res.partner"
    assert admin.delete(f"{url}/1").status_code == 200
    assert [c[2] for c in odoo.calls_to("unlink")] == [[[1]]]
    odoo.failures["unlink"] = OdooValidationError("partner still has invoices")
    refused = admin.delete(f"{url}/2")
    assert refused.status_code == 422 and "invoices" in refused.json()["detail"]
    assert any(r["id"] == 2 for r in odoo.rows["res.partner"])


def test_rest_resources_without_a_delete_endpoint_reject_the_delete(admin: AdminEnv) -> None:
    pid = make_profile(admin)
    config = {
        "name": "items",
        "list_endpoint": {"method": "GET", "path": "/items"},
        "get_endpoint": {"method": "GET", "path": "/items/{id}"},
    }
    assert admin.put(f"{PROFILES}/{pid}/resources/items", json=config).status_code == 200
    response = admin.delete(f"{PROFILES}/{pid}/records/items/1")
    assert response.status_code == 422 and "does not support delete" in response.json()["detail"]


def test_deleting_a_synced_target_record_forgets_its_xref_so_the_next_run_recreates_it(
    admin: AdminEnv,
) -> None:
    fakes = Fakes(admin)
    fakes.seed(3)
    job_id = make_job(admin, fakes)
    first = admin.post(f"/admin/api/jobs/{job_id}/runs", json={}).json()
    assert wait_for_run(admin, first["id"])["counters"]["created"] == 3

    url = f"{PROFILES}/{fakes.dst_id}/records/clients"
    assert admin.delete(f"{url}/2").status_code == 200

    second = admin.post(f"/admin/api/jobs/{job_id}/runs", json={}).json()
    counters: dict[str, Any] = wait_for_run(admin, second["id"])["counters"]
    assert (counters["created"], counters["skipped"], counters["failed"]) == (1, 2, 0)
    assert len(fakes.dst.records["clients"]) == 3


def test_deleting_a_record_of_another_resource_keeps_the_sync_xrefs(admin: AdminEnv) -> None:
    fakes = Fakes(admin)
    fakes.seed(2)
    job_id = make_job(admin, fakes)
    run = admin.post(f"/admin/api/jobs/{job_id}/runs", json={}).json()
    wait_for_run(admin, run["id"])
    fakes.src.seed("customers", {"name": "Zed", "email": "z@x.com"})
    # deleting a SOURCE-side record is not a target deletion: the job's xrefs stay untouched
    assert admin.delete(f"{PROFILES}/{fakes.src_id}/records/customers/3").status_code == 200
    again = admin.post(f"/admin/api/jobs/{job_id}/runs", json={}).json()
    assert wait_for_run(admin, again["id"])["counters"]["skipped"] == 2


# -- write-through to the counterpart -------------------------------------------------------


def bidirectional_pair(admin: AdminEnv) -> tuple[Fakes, int]:
    """Two profiles with one synced customer/client pair under a bidirectional job."""
    fakes = Fakes(admin)
    fakes.seed(1)
    assert save_mapping(admin, reverse_definition()).status_code == 200
    job_id = make_job(admin, fakes, direction="bidirectional", reverse_mapping={"name": "rev"})
    run = admin.post(f"/admin/api/jobs/{job_id}/runs", json={}).json()
    assert wait_for_run(admin, run["id"])["counters"]["created"] == 1
    return fakes, job_id


def test_patch_writes_through_and_reports_the_job_outcome(admin: AdminEnv) -> None:
    fakes, job_id = bidirectional_pair(admin)
    response = admin.patch(
        f"{PROFILES}/{fakes.src_id}/records/customers/1", json={"fields": {"name": "Zed"}}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["fields"]["name"] == "Zed" and body["warnings"] == []
    [outcome] = body["propagation"]
    assert (outcome["job_id"], outcome["action"], outcome["side"]) == (job_id, "updated", "source")
    assert fakes.dst.records["clients"]["1"].fields["full_name"] == "Zed"


def test_patch_with_a_failing_counterpart_is_200_with_a_warning(admin: AdminEnv) -> None:
    from conector_odoo.domain.errors import RemoteUnavailable

    fakes, _ = bidirectional_pair(admin)
    fakes.dst.reject_next(RemoteUnavailable("suwe is down"))
    response = admin.patch(
        f"{PROFILES}/{fakes.src_id}/records/customers/1", json={"fields": {"name": "Zed"}}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["fields"]["name"] == "Zed"
    assert body["propagation"][0]["action"] == "failed"
    assert len(body["warnings"]) == 1 and "suwe is down" in body["warnings"][0]
    assert "customers-sync" in body["warnings"][0]


def test_post_creates_the_record_and_its_counterpart(admin: AdminEnv) -> None:
    fakes, _ = bidirectional_pair(admin)
    response = admin.post(
        f"{PROFILES}/{fakes.src_id}/records/customers",
        json={"fields": {"name": "Cleo", "email": "cleo@x.com"}},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["id"] == "2" and body["fields"]["name"] == "Cleo"
    assert [o["action"] for o in body["propagation"]] == ["created"]
    assert body["warnings"] == []
    assert fakes.dst.records["clients"]["2"].fields["full_name"] == "Cleo"


def test_post_without_a_job_creates_only_the_record(admin: AdminEnv) -> None:
    notes = Notes(admin)
    response = admin.post(notes.url, json={"fields": {"title": "New"}})
    assert response.status_code == 201, response.text
    assert response.json()["propagation"] == []
    assert len(notes.endpoint.records["notes"]) == 4


def test_post_rejects_unknown_and_empty_fields_and_unknown_resources(admin: AdminEnv) -> None:
    notes = Notes(admin)
    for fields in ({"nope": 1}, {"created": "x"}, {}):
        assert admin.post(notes.url, json={"fields": fields}).status_code == 422, fields
    assert admin.post(notes.url, json={"title": "x"}).status_code == 422  # no wrapper
    assert (
        admin.post(f"{PROFILES}/{notes.pid}/records/nope", json={"fields": {"a": 1}}).status_code
        == 404
    )
    assert notes.endpoint.create_calls == 0


def test_delete_writes_through_and_reports_the_job_outcome(admin: AdminEnv) -> None:
    fakes, job_id = bidirectional_pair(admin)
    response = admin.delete(f"{PROFILES}/{fakes.src_id}/records/customers/1")
    assert response.status_code == 200, response.text
    body = response.json()
    assert [(o["job_id"], o["action"]) for o in body["propagation"]] == [(job_id, "deleted")]
    assert body["warnings"] == []
    assert fakes.dst.records["clients"] == {} and fakes.src.records["customers"] == {}
