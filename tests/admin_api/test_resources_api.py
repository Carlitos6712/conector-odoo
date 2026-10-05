import json
from pathlib import Path
from typing import Any

import respx

from conector_odoo.domain.records import Record
from tests.admin_api.conftest import AdminEnv
from tests.admin_api.test_profiles_api import PROFILES, rest_body

ITEMS: dict[str, Any] = {
    "name": "items",
    "label": "Items",
    "list_endpoint": {"method": "GET", "path": "/items"},
    "get_endpoint": {"method": "GET", "path": "/items/{id}"},
    "items_path": "items",
    "pagination": {"strategy": "none"},
}
FIXTURES = Path(__file__).parent.parent / "fixtures"


def make_profile(admin: AdminEnv, **overrides: Any) -> int:
    response = admin.post(PROFILES, json=rest_body(**overrides))
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def test_resource_crud_roundtrip(admin: AdminEnv) -> None:
    pid = make_profile(admin)
    url = f"{PROFILES}/{pid}/resources"
    saved = admin.put(f"{url}/items", json=ITEMS)
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["config"]["name"] == "items" and body["source"] == "manual"
    assert body["config"]["list_endpoint"] == {"method": "GET", "path": "/items"}
    assert body["config"]["pagination"]["strategy"] == "none"
    assert admin.get(f"{url}/items").json()["config"]["items_path"] == "items"
    assert [r["config"]["name"] for r in admin.get(url).json()["items"]] == ["items"]
    assert admin.delete(f"{url}/items").status_code == 204
    assert admin.get(f"{url}/items").status_code == 404


def test_resource_validation_and_name_mismatch(admin: AdminEnv) -> None:
    pid = make_profile(admin)
    url = f"{PROFILES}/{pid}/resources"
    bad = {**ITEMS, "pagination": {"strategy": "cursor"}}
    response = admin.put(f"{url}/items", json=bad)
    assert response.status_code == 422 and response.json()["error"] == "validation_error"
    assert admin.put(f"{url}/other", json=ITEMS).status_code == 422  # path and body disagree
    assert admin.get(f"{PROFILES}/999/resources").status_code == 404


def test_catalog_is_rest_only(admin: AdminEnv) -> None:
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
    assert admin.put(f"{PROFILES}/{pid}/resources/items", json=ITEMS).status_code == 422


@respx.mock
def test_preview_returns_records_and_schema_without_secrets(admin: AdminEnv) -> None:
    pid = make_profile(admin)
    admin.put(f"{PROFILES}/{pid}/resources/items", json=ITEMS)
    route = respx.get("https://api.test/items").respond(
        200, json={"items": [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]}
    )
    response = admin.post(f"{PROFILES}/{pid}/resources/items/preview?limit=2")
    assert response.status_code == 200, response.text
    body = response.json()
    assert [r["fields"]["name"] for r in body["records"]] == ["A", "B"]
    assert {f["name"] for f in body["schema"]["fields"]} >= {"id", "name"}
    assert route.calls.last.request.headers["authorization"] == "Bearer tok-SECRET-0123456789"
    assert "tok-SECRET" not in response.text


@respx.mock
def test_preview_remote_failure_is_a_clean_502(admin: AdminEnv) -> None:
    pid = make_profile(admin)
    admin.put(f"{PROFILES}/{pid}/resources/items", json=ITEMS)
    respx.get("https://api.test/items").respond(401, json={"detail": "tok-SECRET-0123456789"})
    response = admin.post(f"{PROFILES}/{pid}/resources/items/preview")
    assert response.status_code == 502
    assert response.json()["error"] == "remote_auth_error"
    assert "tok-SECRET" not in response.text


def test_preview_unknown_resource_is_404(admin: AdminEnv) -> None:
    pid = make_profile(admin)
    assert admin.post(f"{PROFILES}/{pid}/resources/nope/preview").status_code == 404


def test_discover_lists_the_catalog_for_rest_profiles(admin: AdminEnv) -> None:
    pid = make_profile(admin)
    admin.put(f"{PROFILES}/{pid}/resources/items", json=ITEMS)
    response = admin.post(f"{PROFILES}/{pid}/discover")
    assert response.status_code == 200
    assert response.json()["items"] == [{"name": "items", "label": "Items"}]


def test_discover_odoo_models_uses_ir_model(admin: AdminEnv) -> None:
    from conector_odoo.application.resources import DiscoveredResource  # noqa: F401

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

    class FakeOdoo:
        async def iter_batches(self, resource: str, flt: Any, size: int) -> Any:
            assert resource == "ir.model"
            yield [Record("1", {"model": "res.partner", "name": "Contact"})]

        async def aclose(self) -> None:
            return None

    admin.client.app.state.admin.endpoints.build_odoo = lambda profile, secrets: FakeOdoo()  # type: ignore[attr-defined]
    response = admin.post(f"{PROFILES}/{pid}/discover")
    assert response.status_code == 200, response.text
    assert response.json()["items"] == [{"name": "res.partner", "label": "Contact"}]


def test_openapi_import_from_document_returns_candidates_without_saving(admin: AdminEnv) -> None:
    pid = make_profile(admin)
    document = (FIXTURES / "suwe_openapi_enriched.json").read_text()
    response = admin.post(
        f"{PROFILES}/{pid}/resources/import", json={"document": document, "base_path": "/api/v1"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["candidates"] and isinstance(body["warnings"], list)
    names = [c["name"] for c in body["candidates"]]
    assert admin.get(f"{PROFILES}/{pid}/resources").json()["items"] == []
    first = body["candidates"][0]
    saved = admin.put(f"{PROFILES}/{pid}/resources/{names[0]}", json={**first, "source": "openapi"})
    assert saved.status_code == 200 and saved.json()["source"] == "openapi"


@respx.mock
def test_openapi_import_from_url(admin: AdminEnv) -> None:
    pid = make_profile(admin)
    spec = {
        "openapi": "3.0.0",
        "paths": {"/things": {"get": {"responses": {"200": {"description": "ok"}}}}},
    }
    respx.get("https://docs.test/openapi.json").respond(200, content=json.dumps(spec).encode())
    response = admin.post(
        f"{PROFILES}/{pid}/resources/import", json={"url": "https://docs.test/openapi.json"}
    )
    assert response.status_code == 200, response.text
    assert [c["name"] for c in response.json()["candidates"]] == ["things"]


def test_openapi_import_needs_exactly_one_source_and_rejects_garbage(admin: AdminEnv) -> None:
    pid = make_profile(admin)
    url = f"{PROFILES}/{pid}/resources/import"
    assert admin.post(url, json={}).status_code == 422
    assert admin.post(url, json={"url": "https://x.test/a", "document": "{}"}).status_code == 422
    garbage = admin.post(url, json={"document": "not an openapi document"})
    assert garbage.status_code == 422 and garbage.json()["error"] == "import_failed"
