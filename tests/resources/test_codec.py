import json
from dataclasses import replace

import pytest

from conector_odoo.domain.errors import ResourceConfigInvalid
from conector_odoo.domain.records import FieldSpec, FieldType
from conector_odoo.domain.resource_codec import (
    resource_config_from_json,
    resource_config_to_json,
    validate_resource_config,
)
from conector_odoo.domain.resources import (
    EndpointSpec,
    PaginationConfig,
    PaginationStrategy,
    ResourceConfig,
)


def full() -> ResourceConfig:
    return ResourceConfig(
        name="organization.clients",
        label="Clients",
        list_endpoint=EndpointSpec("GET", "/organization/clients"),
        get_endpoint=EndpointSpec("GET", "/organization/clients/{id}"),
        create_endpoint=EndpointSpec("POST", "/organization/clients"),
        update_endpoint=EndpointSpec("PATCH", "/organization/clients/{id}"),
        items_path="items",
        item_path="data",
        id_field="uuid",
        pagination=PaginationConfig(
            strategy=PaginationStrategy.PAGE, total_pages_path="total_pages", max_pages=50
        ),
        filter_param_map={"email": "q_email"},
        since_param="updated_since",
        schema_fields=(
            FieldSpec("uuid", FieldType.STRING, required=True, readonly=True, label="UUID"),
            FieldSpec("kind", FieldType.STRING, choices=("a", "b"), relation="kinds"),
        ),
    )


def test_round_trip_is_lossless_and_versioned() -> None:
    cfg = full()
    text = resource_config_to_json(cfg)
    assert json.loads(text)["version"] == 1
    assert resource_config_from_json(text) == cfg


def test_round_trip_of_minimal_config() -> None:
    cfg = ResourceConfig(name="x", label="X", list_endpoint=EndpointSpec("GET", "/x"))
    assert resource_config_from_json(resource_config_to_json(cfg)) == cfg


@pytest.mark.parametrize(
    "text",
    ["", "not json", "[]", '{"version": 99, "name": "x"}', '{"name": "x"}'],
)
def test_unknown_or_malformed_json_is_a_domain_error(text: str) -> None:
    with pytest.raises(ResourceConfigInvalid):
        resource_config_from_json(text)


def test_wrong_field_types_are_a_domain_error() -> None:
    data = json.loads(resource_config_to_json(full()))
    data["pagination"]["max_pages"] = "many"
    with pytest.raises(ResourceConfigInvalid, match="max_pages"):
        resource_config_from_json(json.dumps(data))
    data = json.loads(resource_config_to_json(full()))
    data["pagination"]["strategy"] = "teleport"
    with pytest.raises(ResourceConfigInvalid, match="strategy"):
        resource_config_from_json(json.dumps(data))
    data = json.loads(resource_config_to_json(full()))
    data["schema_fields"][0]["type"] = "blob"
    with pytest.raises(ResourceConfigInvalid, match="type"):
        resource_config_from_json(json.dumps(data))


def test_valid_config_passes() -> None:
    validate_resource_config(full())


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"name": " "}, "name"),
        ({"name": "has space"}, "name"),
        ({"id_field": ""}, "id_field"),
        ({"list_endpoint": EndpointSpec("DELETE", "/x")}, "method"),
        ({"list_endpoint": EndpointSpec("GET", "x")}, "path"),
        ({"list_endpoint": EndpointSpec("GET", "https://evil.test/x")}, "path"),
        ({"list_endpoint": EndpointSpec("GET", "/x/{id}")}, "{id}"),
        ({"get_endpoint": EndpointSpec("GET", "/x")}, "{id}"),
        ({"get_endpoint": EndpointSpec("GET", "/x/{client_id}")}, "{client_id}"),
        ({"update_endpoint": EndpointSpec("PATCH", "/x")}, "{id}"),
        ({"create_endpoint": EndpointSpec("POST", "/x/{id}")}, "{id}"),
        ({"get_endpoint": EndpointSpec("POST", "/x/{id}")}, "method"),
        ({"filter_param_map": {"": "q"}}, "filter_param_map"),
        (
            {
                "schema_fields": (
                    FieldSpec("a", FieldType.STRING),
                    FieldSpec("a", FieldType.STRING),
                )
            },
            "duplicate",
        ),
    ],
)
def test_invalid_endpoint_shapes_are_rejected(change: dict[str, object], message: str) -> None:
    with pytest.raises(ResourceConfigInvalid, match=message):
        validate_resource_config(replace(full(), **change))  # type: ignore[arg-type]


def test_a_resource_needs_at_least_one_endpoint() -> None:
    with pytest.raises(ResourceConfigInvalid, match="endpoint"):
        validate_resource_config(ResourceConfig(name="x", label="X"))


@pytest.mark.parametrize(
    "pagination",
    [
        PaginationConfig(strategy=PaginationStrategy.PAGE, page_param=""),
        PaginationConfig(strategy=PaginationStrategy.PAGE, size_param=" "),
        PaginationConfig(strategy=PaginationStrategy.PAGE, first_page=-1),
        PaginationConfig(strategy=PaginationStrategy.OFFSET, offset_param=""),
        PaginationConfig(strategy=PaginationStrategy.OFFSET, limit_param=""),
        PaginationConfig(strategy=PaginationStrategy.CURSOR, cursor_param=""),
        PaginationConfig(strategy=PaginationStrategy.CURSOR, next_cursor_path=None),
        PaginationConfig(max_pages=0),
    ],
)
def test_inconsistent_pagination_is_rejected(pagination: PaginationConfig) -> None:
    with pytest.raises(ResourceConfigInvalid, match="pagination"):
        validate_resource_config(replace(full(), pagination=pagination))


def test_pagination_needs_a_list_endpoint() -> None:
    cfg = ResourceConfig(
        name="x",
        label="X",
        get_endpoint=EndpointSpec("GET", "/x/{id}"),
        pagination=PaginationConfig(strategy=PaginationStrategy.PAGE),
    )
    with pytest.raises(ResourceConfigInvalid, match="pagination"):
        validate_resource_config(cfg)
