import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from conector_odoo.domain.errors import OpenApiImportError
from conector_odoo.domain.records import FieldType
from conector_odoo.domain.resource_codec import validate_resource_config
from conector_odoo.domain.resources import EndpointSpec, PaginationStrategy, ResourceConfig
from conector_odoo.infrastructure.openapi.importer import ImportReport, OpenApiImporter

FIXTURES = Path(__file__).parent.parent / "fixtures"

OK = {"200": {"description": "ok"}}


def doc(paths: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {"openapi": "3.0.3", "info": {"title": "t", "version": "1"}, "paths": paths, **extra}


def resp(schema: dict[str, Any]) -> dict[str, Any]:
    return {"200": {"content": {"application/json": {"schema": schema}}}}


def run(document: dict[str, Any], **kwargs: Any) -> ImportReport:
    return OpenApiImporter().parse(json.dumps(document), **kwargs)


def one(report: ImportReport, name: str | None = None) -> ResourceConfig:
    matches = [c for c in report.candidates if name is None or c.name == name]
    assert len(matches) == 1, [c.name for c in report.candidates]
    return matches[0]


def query(*names: str) -> list[dict[str, Any]]:
    return [{"name": n, "in": "query", "schema": {"type": "string"}} for n in names]


def listing(params: list[dict[str, Any]], schema: dict[str, Any] | None = None) -> dict[str, Any]:
    body = schema or {"type": "array", "items": {"type": "object", "properties": {"id": {}}}}
    return {"/things": {"get": {"parameters": params, "responses": resp(body)}}}


# -- real and enriched SUWE fixtures -------------------------------------------------------


def test_enriched_suwe_spec_yields_clients_with_page_pagination() -> None:
    report = OpenApiImporter().parse((FIXTURES / "suwe_openapi_enriched.json").read_bytes())
    cfg = one(report, "organization.clients")
    assert cfg.label == "Clients"
    assert cfg.list_endpoint == EndpointSpec("GET", "/organization/clients")
    assert cfg.get_endpoint == EndpointSpec("GET", "/organization/clients/{id}")
    assert cfg.create_endpoint == EndpointSpec("POST", "/organization/clients")
    assert cfg.update_endpoint is None
    assert cfg.items_path == "items"
    assert cfg.id_field == "uuid"
    assert cfg.pagination.strategy is PaginationStrategy.PAGE
    assert (cfg.pagination.page_param, cfg.pagination.size_param) == ("page", "page_size")
    assert cfg.pagination.total_pages_path == "total_pages"
    assert cfg.filter_param_map == {"status": "status"}
    fields = {f.name: f for f in cfg.schema_fields}
    assert fields["uuid"].required and fields["name"].required and not fields["city"].required
    assert fields["establishment"].type is FieldType.INTEGER
    assert fields["acceptance"].type is FieldType.NUMBER
    assert fields["created"].type is FieldType.DATETIME
    assert fields["services"].type is FieldType.OBJECT
    assert fields["status"].choices == ("active", "inactive")
    assert fields["name"].label == "Name"
    for candidate in report.candidates:
        validate_resource_config(candidate)


def test_real_suwe_spec_without_schemas_is_handled_with_warnings() -> None:
    content = (FIXTURES / "suwe_openapi_real.json").read_bytes()
    report = OpenApiImporter().parse(content, base_path="/api/v1")
    names = {c.name for c in report.candidates}
    assert {"organization.clients", "organization.stores", "organization.partners"} <= names
    clients = one(report, "organization.clients")
    assert clients.list_endpoint == EndpointSpec("GET", "/organization/clients")
    assert clients.get_endpoint == EndpointSpec("GET", "/organization/clients/{id}")
    assert clients.create_endpoint == EndpointSpec("POST", "/organization/clients")
    assert clients.pagination.strategy is PaginationStrategy.NONE
    assert clients.id_field == "id"
    partners = one(report, "organization.partners")
    assert partners.update_endpoint == EndpointSpec("PATCH", "/organization/partners/{id}")
    joined = "\n".join(report.warnings)
    assert "/organization/clients/options" in joined  # shadowed by the item template
    assert "/organization/clients/{client_id}/contacts" in joined  # nested
    assert "/{path}" in joined  # catch-all
    assert "organization.clients" in joined  # no response schema: items_path/id guessed
    assert "organization.clients.options" not in names


# -- documents and base paths ----------------------------------------------------------------


def test_swagger_2_with_base_path_and_definitions_in_yaml() -> None:
    swagger = {
        "swagger": "2.0",
        "basePath": "/v2",
        "paths": {
            "/v2/pets": {
                "get": {
                    "parameters": [
                        {"name": "offset", "in": "query", "type": "integer"},
                        {"name": "limit", "in": "query", "type": "integer"},
                    ],
                    "responses": {
                        "200": {"schema": {"$ref": "#/definitions/PetList"}},
                    },
                },
                "post": {"responses": {"201": {"schema": {"$ref": "#/definitions/Pet"}}}},
            },
            "/v2/pets/{petId}": {
                "get": {"responses": {"200": {"schema": {"$ref": "#/definitions/Pet"}}}},
                "put": {"responses": {"200": {}}},
            },
        },
        "definitions": {
            "Pet": {
                "type": "object",
                "required": ["pet_id"],
                "properties": {
                    "pet_id": {"type": "integer"},
                    "born": {"type": "string", "format": "date"},
                    "alive": {"type": "boolean"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
            },
            "PetList": {
                "type": "object",
                "properties": {
                    "results": {"type": "array", "items": {"$ref": "#/definitions/Pet"}},
                    "total": {"type": "integer"},
                },
            },
        },
    }
    report = OpenApiImporter().parse(yaml.safe_dump(swagger).encode())
    cfg = one(report, "pets")
    assert cfg.list_endpoint == EndpointSpec("GET", "/pets")
    assert cfg.get_endpoint == EndpointSpec("GET", "/pets/{id}")
    assert cfg.update_endpoint == EndpointSpec("PUT", "/pets/{id}")
    assert cfg.items_path == "results"
    assert cfg.id_field == "pet_id"
    assert cfg.pagination.strategy is PaginationStrategy.OFFSET
    assert cfg.pagination.total_path == "total"
    types = {f.name: f.type for f in cfg.schema_fields}
    assert types == {
        "pet_id": FieldType.INTEGER,
        "born": FieldType.DATE,
        "alive": FieldType.BOOLEAN,
        "tags": FieldType.ARRAY,
    }


@pytest.mark.parametrize(
    ("servers", "expected"),
    [
        ([{"url": "https://api.example.com/v1"}], "/things"),
        ([{"url": "/v1/"}], "/things"),
        (
            [{"url": "https://{env}.example.com/{ver}", "variables": {"ver": {"default": "v1"}}}],
            "/things",
        ),
        ([{"url": "https://api.example.com"}], "/v1/things"),
        ([], "/v1/things"),
    ],
)
def test_servers_url_path_is_stripped(servers: list[dict[str, Any]], expected: str) -> None:
    spec = doc({"/v1/things": {"get": {"responses": OK}}}, servers=servers)
    cfg = one(run(spec))
    assert cfg.list_endpoint == EndpointSpec("GET", expected)


def test_explicit_base_path_wins_over_servers() -> None:
    spec = doc({"/api/things": {"get": {"responses": OK}}}, servers=[{"url": "/other"}])
    cfg = one(run(spec, base_path="/api"))
    assert cfg.list_endpoint == EndpointSpec("GET", "/things")


def test_paths_outside_the_base_path_are_kept_with_a_warning() -> None:
    spec = doc({"/v1/a": {"get": {"responses": OK}}, "/b": {"get": {"responses": OK}}})
    report = run(spec, base_path="/v1")
    assert {c.name for c in report.candidates} == {"a", "b"}
    assert any("/b" in w and "base path" in w for w in report.warnings)


# -- $ref ------------------------------------------------------------------------------------


def test_ref_cycles_and_deep_chains_do_not_hang() -> None:
    schemas: dict[str, Any] = {
        "Node": {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "parent": {"$ref": "#/components/schemas/Node"},
            },
        },
        "A": {"$ref": "#/components/schemas/B"},
        "B": {"$ref": "#/components/schemas/A"},
    }
    for i in range(60):
        schemas[f"C{i}"] = {"$ref": f"#/components/schemas/C{i + 1}"}
    spec = doc(
        {
            "/nodes": {
                "get": {
                    "responses": resp(
                        {"type": "array", "items": {"$ref": "#/components/schemas/Node"}}
                    )
                }
            },
            "/loops": {
                "get": {
                    "responses": resp(
                        {"type": "array", "items": {"$ref": "#/components/schemas/A"}}
                    )
                }
            },
            "/deep": {
                "get": {
                    "responses": resp(
                        {"type": "array", "items": {"$ref": "#/components/schemas/C0"}}
                    )
                }
            },
        },
        components={"schemas": schemas},
    )
    report = run(spec)
    assert {f.name for f in one(report, "nodes").schema_fields} == {"id", "parent"}
    assert one(report, "loops").schema_fields == ()
    assert one(report, "deep").schema_fields == ()


def test_non_local_refs_are_ignored_and_never_fetched() -> None:
    spec = doc({"/x": {"get": {"responses": resp({"$ref": "http://127.0.0.1:1/schema.json"})}}})
    assert one(run(spec)).schema_fields == ()


def test_all_of_properties_are_merged() -> None:
    spec = doc(
        {
            "/x": {
                "get": {
                    "responses": resp(
                        {
                            "type": "array",
                            "items": {
                                "allOf": [
                                    {"type": "object", "properties": {"id": {"type": "integer"}}},
                                    {"type": "object", "properties": {"name": {"type": "string"}}},
                                ]
                            },
                        }
                    )
                }
            }
        }
    )
    assert [f.name for f in one(run(spec)).schema_fields] == ["id", "name"]


# -- list shape, id field --------------------------------------------------------------------


def test_root_array_has_empty_items_path() -> None:
    assert one(run(doc(listing([])))).items_path == ""


@pytest.mark.parametrize("prop", ["items", "data", "results", "records"])
def test_items_path_is_the_array_property(prop: str) -> None:
    schema = {
        "type": "object",
        "properties": {
            "total": {"type": "integer"},
            prop: {"type": "array", "items": {"type": "object"}},
        },
    }
    assert one(run(doc(listing([], schema)))).items_path == prop


def item_spec(props: dict[str, Any], param: str = "thing_id") -> dict[str, Any]:
    schema = {"type": "object", "properties": props}
    return doc(
        {
            "/things": {"get": {"responses": resp({"type": "array", "items": schema})}},
            f"/things/{{{param}}}": {"get": {"responses": resp(schema)}},
        }
    )


@pytest.mark.parametrize(
    ("props", "param", "expected"),
    [
        ({"uuid": {}, "id": {}}, "thing_id", "id"),
        ({"uuid": {}, "name": {}}, "thing_id", "uuid"),
        ({"thing_id": {}, "name": {}}, "x", "thing_id"),
        ({"code": {}, "name": {}}, "code", "code"),
        ({"name": {}}, "slug", "slug"),
    ],
)
def test_id_field_detection(props: dict[str, Any], param: str, expected: str) -> None:
    assert one(run(item_spec(props, param))).id_field == expected


def test_update_prefers_patch_over_put() -> None:
    spec = doc(
        {
            "/things/{id}": {
                "put": {"responses": OK},
                "patch": {"responses": OK},
            }
        }
    )
    assert one(run(spec)).update_endpoint == EndpointSpec("PATCH", "/things/{id}")


def test_delete_on_the_item_path_becomes_the_delete_endpoint() -> None:
    spec = doc({"/things/{id}": {"get": {"responses": OK}, "delete": {"responses": OK}}})
    cfg = one(run(spec))
    assert cfg.delete_endpoint == EndpointSpec("DELETE", "/things/{id}")
    assert one(run(doc({"/things/{id}": {"get": {"responses": OK}}}))).delete_endpoint is None


def test_item_wrapped_in_data_sets_item_path() -> None:
    wrapped = {
        "type": "object",
        "properties": {
            "data": {"type": "object", "properties": {"id": {"type": "integer"}}},
        },
    }
    spec = doc({"/things/{id}": {"get": {"responses": resp(wrapped)}}})
    cfg = one(run(spec))
    assert cfg.item_path == "data"
    assert [f.name for f in cfg.schema_fields] == ["id"]


# -- pagination ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("params", "strategy", "expected"),
    [
        (
            ("page", "page_size"),
            PaginationStrategy.PAGE,
            {"page_param": "page", "size_param": "page_size"},
        ),
        (("page", "per_page"), PaginationStrategy.PAGE, {"size_param": "per_page"}),
        (("page", "size"), PaginationStrategy.PAGE, {"size_param": "size"}),
        (("page", "limit"), PaginationStrategy.PAGE, {"size_param": "limit"}),
        (
            ("offset", "limit"),
            PaginationStrategy.OFFSET,
            {"offset_param": "offset", "limit_param": "limit"},
        ),
        (("cursor",), PaginationStrategy.CURSOR, {"cursor_param": "cursor"}),
        (
            ("after", "limit"),
            PaginationStrategy.CURSOR,
            {"cursor_param": "after", "limit_param": "limit"},
        ),
        (
            ("page_token", "page_size"),
            PaginationStrategy.CURSOR,
            {"cursor_param": "page_token", "limit_param": "page_size"},
        ),
        (("next",), PaginationStrategy.CURSOR, {"cursor_param": "next"}),
        (("q", "sort"), PaginationStrategy.NONE, {}),
    ],
)
def test_pagination_detection(
    params: tuple[str, ...], strategy: PaginationStrategy, expected: dict[str, str]
) -> None:
    cfg = one(run(doc(listing(query(*params)))))
    assert cfg.pagination.strategy is strategy
    for key, value in expected.items():
        assert getattr(cfg.pagination, key) == value
    validate_resource_config(cfg)


def test_cursor_without_a_known_next_path_warns_and_guesses() -> None:
    report = run(doc(listing(query("cursor"))))
    assert one(report).pagination.next_cursor_path == "next_cursor"
    assert any("next_cursor_path" in w for w in report.warnings)


def test_cursor_next_path_comes_from_the_response() -> None:
    schema = {
        "type": "object",
        "properties": {
            "items": {"type": "array", "items": {"type": "object"}},
            "nextPageToken": {"type": "string"},
        },
    }
    cfg = one(run(doc(listing(query("page_token"), schema))))
    assert cfg.pagination.next_cursor_path == "nextPageToken"


def test_since_param_and_ref_parameters_are_recognised() -> None:
    spec = doc(
        {
            "/things": {
                "get": {"parameters": [{"$ref": "#/components/parameters/Since"}], "responses": OK}
            }
        },
        components={"parameters": {"Since": {"name": "updated_since", "in": "query"}}},
    )
    assert one(run(spec)).since_param == "updated_since"


# -- classification and warnings -------------------------------------------------------------


def test_paths_without_list_get_pairs_still_become_candidates() -> None:
    spec = doc(
        {
            "/only-list": {"get": {"responses": OK}},
            "/only-item/{id}": {"get": {"responses": OK}},
            "/only-post": {"post": {"responses": OK}},
            "/only-delete/{id}": {"delete": {"responses": OK}},
        }
    )
    report = run(spec)
    by = {c.name: c for c in report.candidates}
    assert by["only_list"].get_endpoint is None and by["only_list"].list_endpoint
    assert by["only_item"].list_endpoint is None and by["only_item"].get_endpoint
    assert by["only_post"].create_endpoint and by["only_post"].list_endpoint is None
    assert "only_delete" not in by
    assert any("/only-delete/{id}" in w for w in report.warnings)


def test_unclassifiable_paths_produce_warnings_not_errors() -> None:
    spec = doc(
        {
            "/": {"get": {"responses": OK}},
            "/a/{x}/b/{y}": {"get": {"responses": OK}},
            "/a/{x}/children": {"get": {"responses": OK}},
            "/a/{x}/{y}": {"get": {"responses": OK}},
            "/ok": {"get": {"responses": OK}},
        }
    )
    report = run(spec)
    assert [c.name for c in report.candidates] == ["ok"]
    for path in ("/", "/a/{x}/b/{y}", "/a/{x}/children", "/a/{x}/{y}"):
        assert any(path in w for w in report.warnings), path


def test_names_are_unique_within_the_import() -> None:
    spec = doc({"/a-b": {"get": {"responses": OK}}, "/a_b": {"get": {"responses": OK}}})
    assert sorted(c.name for c in run(spec).candidates) == ["a_b", "a_b_2"]


def test_trailing_slash_variants_merge() -> None:
    spec = doc({"/x/": {"get": {"responses": OK}}, "/x": {"post": {"responses": OK}}})
    cfg = one(run(spec))
    assert cfg.list_endpoint and cfg.create_endpoint


def test_a_spec_without_paths_reports_a_warning() -> None:
    report = run({"openapi": "3.1.0"})
    assert report.candidates == ()
    assert report.warnings


# -- loading ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [b"", b"just text: [", b"[1, 2]", b'{"info": {}}', b'{"openapi": "4.0.0", "paths": {}}'],
)
def test_unsupported_documents_raise(content: bytes) -> None:
    with pytest.raises(OpenApiImportError):
        OpenApiImporter().parse(content)


def test_yaml_is_parsed_with_safe_load_only() -> None:
    evil = b"openapi: 3.0.0\npaths: !!python/object/apply:os.getcwd []\n"
    with pytest.raises(OpenApiImportError):
        OpenApiImporter().parse(evil)


def test_yaml_documents_are_accepted() -> None:
    text = yaml.safe_dump(doc({"/things": {"get": {"responses": OK}}}))
    assert one(OpenApiImporter().parse(text)).name == "things"


def test_raw_content_is_size_capped() -> None:
    importer = OpenApiImporter(max_bytes=100)
    with pytest.raises(OpenApiImportError, match="larger"):
        importer.parse(b" " * 101)
