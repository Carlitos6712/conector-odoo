from typing import Any

from tests.admin_api.conftest import AdminEnv
from tests.admin_api.world import (
    Fakes,
    forward_definition,
    reverse_definition,
    save_mapping,
)

MAPPINGS = "/admin/api/mappings"


def test_save_creates_versions_and_identical_saves_do_not(admin: AdminEnv) -> None:
    first = save_mapping(admin, forward_definition())
    assert first.status_code == 200, first.text
    assert (first.json()["mapping"]["version"], first.json()["created"]) == (1, True)
    again = save_mapping(admin, forward_definition())
    assert (again.json()["mapping"]["version"], again.json()["created"]) == (1, False)
    changed = forward_definition()
    changed["rules"].append({"target": "phone", "expr": {"type": "constant", "value": "n/a"}})
    third = save_mapping(admin, changed)
    assert third.json()["mapping"]["version"] == 2
    versions = admin.get(f"{MAPPINGS}/fwd/versions").json()["items"]
    assert [v["version"] for v in versions] == [1, 2]
    assert (
        admin.get(f"{MAPPINGS}/fwd?version=1").json()["definition"]["rules"][0]["target"]
        == "full_name"
    )
    assert admin.get(f"{MAPPINGS}/fwd").json()["version"] == 2
    assert [m["name"] for m in admin.get(MAPPINGS).json()["items"]] == ["fwd"]


def test_invalid_mappings_are_422_with_a_precise_path(admin: AdminEnv) -> None:
    broken: dict[str, Any] = forward_definition()
    broken["rules"][0]["expr"] = {"type": "nonsense"}
    response = save_mapping(admin, broken)
    assert response.status_code == 422 and response.json()["error"] == "validation_error"
    assert "rules[0]" in response.json()["detail"]
    mismatch = admin.put(f"{MAPPINGS}/other", json={"definition": forward_definition()})
    assert mismatch.status_code == 422
    duplicate_target = forward_definition()
    duplicate_target["rules"].append(duplicate_target["rules"][0])
    semantic = save_mapping(admin, duplicate_target)
    assert semantic.status_code == 422 and semantic.json()["issues"]


def test_unknown_mapping_is_404_and_delete_works(admin: AdminEnv) -> None:
    assert admin.get(f"{MAPPINGS}/nope").status_code == 404
    assert admin.get(f"{MAPPINGS}/nope/versions").status_code == 404
    save_mapping(admin, forward_definition())
    assert admin.delete(f"{MAPPINGS}/fwd").status_code == 204
    assert admin.delete(f"{MAPPINGS}/fwd").status_code == 404


def test_dry_run_a_draft_maps_a_sample_without_writing(admin: AdminEnv) -> None:
    fakes = Fakes(admin)
    fakes.seed(3)
    body = {
        "definition": forward_definition(),
        "source_profile_id": fakes.src_id,
        "target_profile_id": fakes.dst_id,
        "limit": 2,
    }
    response = admin.post(f"{MAPPINGS}/dry-run", json=body)
    assert response.status_code == 200, response.text
    report = response.json()
    assert (report["total"], report["ok"], report["with_errors"]) == (2, 2, 0)
    assert report["items"][0]["mapped_fields"] == {"full_name": "Ana 1", "email": "ana1@x.com"}
    assert not fakes.dst.records["clients"]


def test_dry_run_a_saved_mapping_and_input_rules(admin: AdminEnv) -> None:
    fakes = Fakes(admin)
    fakes.seed(1)
    save_mapping(admin, forward_definition())
    ids = {"source_profile_id": fakes.src_id, "target_profile_id": fakes.dst_id}
    saved = admin.post(f"{MAPPINGS}/dry-run", json={"name": "fwd", **ids})
    assert saved.status_code == 200 and saved.json()["total"] == 1
    neither = admin.post(f"{MAPPINGS}/dry-run", json=ids)
    both = admin.post(f"{MAPPINGS}/dry-run", json={"name": "fwd", "definition": {}, **ids})
    assert neither.status_code == both.status_code == 422
    assert admin.post(f"{MAPPINGS}/dry-run", json={"name": "ghost", **ids}).status_code == 404
    too_many = admin.post(f"{MAPPINGS}/dry-run", json={"name": "fwd", "limit": 500, **ids})
    assert too_many.status_code == 422


def test_save_with_profiles_validates_against_live_schemas(admin: AdminEnv) -> None:
    fakes = Fakes(admin)
    definition = forward_definition()
    definition["rules"].append(
        {"target": "no_such_field", "expr": {"type": "constant", "value": 1}}
    )
    response = admin.put(
        f"{MAPPINGS}/fwd",
        json={
            "definition": definition,
            "source_profile_id": fakes.src_id,
            "target_profile_id": fakes.dst_id,
        },
    )
    assert response.status_code in (200, 422)
    issues = response.json().get("issues") or response.json().get("warnings")
    assert any("no_such_field" in i["path"] or "no_such_field" in i["message"] for i in issues)


def test_suggest_proposes_direct_rules_for_matching_fields(admin: AdminEnv) -> None:
    fakes = Fakes(admin)
    response = admin.post(
        f"{MAPPINGS}/suggest",
        json={
            "source_profile_id": fakes.src_id,
            "source_resource": "customers",
            "target_profile_id": fakes.dst_id,
            "target_resource": "clients",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [r["target"] for r in body["definition"]["rules"]] == ["email"]
    assert body["unmatched_source"] == ["name"] and body["unmatched_target"] == ["full_name"]


def test_reverse_mapping_fixture_is_valid(admin: AdminEnv) -> None:
    assert save_mapping(admin, reverse_definition()).status_code == 200
