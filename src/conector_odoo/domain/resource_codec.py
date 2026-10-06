"""Validation and versioned JSON (de)serialisation of ``ResourceConfig``.

Pure domain: stdlib only. Anything unknown or malformed raises ``ResourceConfigInvalid`` with a
message naming the offending part, so the admin can fix it instead of seeing a stack trace.
"""

import json
import re
from collections.abc import Mapping
from typing import Any

from conector_odoo.domain.errors import ResourceConfigInvalid
from conector_odoo.domain.records import FieldSpec, FieldType
from conector_odoo.domain.resources import (
    EndpointSpec,
    PaginationConfig,
    PaginationStrategy,
    ResourceConfig,
)

SCHEMA_VERSION = 1

_NAME = re.compile(r"^[A-Za-z0-9_.\-]+$")
_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")
_METHODS = {
    "list": {"GET"},
    "get": {"GET"},
    "create": {"POST", "PUT"},
    "update": {"PUT", "PATCH", "POST"},
}


# -- validation ------------------------------------------------------------------------------


def validate_resource_config(cfg: ResourceConfig) -> None:
    """Raises ``ResourceConfigInvalid`` unless the config is safe to store and run."""
    if not _NAME.match(cfg.name):
        raise ResourceConfigInvalid(
            "name must be non-empty and use only letters, digits, '.', '_' and '-'"
        )
    if not cfg.id_field.strip():
        raise ResourceConfigInvalid("id_field must not be empty")
    endpoints = {
        "list": cfg.list_endpoint,
        "get": cfg.get_endpoint,
        "create": cfg.create_endpoint,
        "update": cfg.update_endpoint,
    }
    if not any(endpoints.values()):
        raise ResourceConfigInvalid("a resource needs at least one endpoint")
    for operation, spec in endpoints.items():
        if spec is not None:
            _validate_endpoint(operation, spec)
    _validate_pagination(cfg.pagination, has_list=cfg.list_endpoint is not None)
    for key, value in cfg.filter_param_map.items():
        if not key.strip() or not value.strip():
            raise ResourceConfigInvalid("filter_param_map entries must be non-empty")
    names = [spec.name for spec in cfg.schema_fields]
    if len(names) != len(set(names)):
        raise ResourceConfigInvalid("schema_fields has a duplicate field name")


def _validate_endpoint(operation: str, spec: EndpointSpec) -> None:
    if spec.method not in _METHODS[operation]:
        allowed = "/".join(sorted(_METHODS[operation]))
        raise ResourceConfigInvalid(f"{operation} endpoint method must be {allowed}")
    path = spec.path
    if not path.startswith("/") or path.startswith("//") or any(c.isspace() for c in path):
        raise ResourceConfigInvalid(
            f"{operation} endpoint path must start with '/' and be relative to the base URL"
        )
    others = [p for p in _PLACEHOLDER.findall(path) if p != "id"]
    if others:
        raise ResourceConfigInvalid(
            f"{operation} endpoint path may only use the {{id}} placeholder, not {{{others[0]}}}"
        )
    if "{" in _PLACEHOLDER.sub("", path) or "}" in _PLACEHOLDER.sub("", path):
        raise ResourceConfigInvalid(f"{operation} endpoint path has an unbalanced brace")
    needs_id = operation in ("get", "update")
    if needs_id != ("{id}" in path):
        raise ResourceConfigInvalid(
            f"{operation} endpoint path {'must' if needs_id else 'must not'} contain {{id}}"
        )


def _validate_pagination(pg: PaginationConfig, *, has_list: bool) -> None:
    def fail(reason: str) -> ResourceConfigInvalid:
        return ResourceConfigInvalid(f"pagination: {reason}")

    if pg.max_pages < 1:
        raise fail("max_pages must be at least 1")
    if pg.strategy is PaginationStrategy.NONE:
        return
    if not has_list:
        raise fail("a list endpoint is required")
    if pg.strategy is PaginationStrategy.PAGE:
        if not pg.page_param.strip() or not pg.size_param.strip():
            raise fail("page_param and size_param are required for the page strategy")
        if pg.first_page < 0:
            raise fail("first_page must not be negative")
    elif pg.strategy is PaginationStrategy.OFFSET:
        if not pg.offset_param.strip() or not pg.limit_param.strip():
            raise fail("offset_param and limit_param are required for the offset strategy")
    elif not pg.cursor_param.strip() or not (pg.next_cursor_path or "").strip():
        raise fail("cursor_param and next_cursor_path are required for the cursor strategy")


# -- serialisation ---------------------------------------------------------------------------


def resource_config_to_json(cfg: ResourceConfig) -> str:
    pg = cfg.pagination
    data: dict[str, Any] = {
        "version": SCHEMA_VERSION,
        "name": cfg.name,
        "label": cfg.label,
        "endpoints": {
            op: {"method": spec.method, "path": spec.path}
            for op, spec in (
                ("list", cfg.list_endpoint),
                ("get", cfg.get_endpoint),
                ("create", cfg.create_endpoint),
                ("update", cfg.update_endpoint),
            )
            if spec is not None
        },
        "items_path": cfg.items_path,
        "item_path": cfg.item_path,
        "id_field": cfg.id_field,
        "pagination": {
            "strategy": pg.strategy.value,
            "page_param": pg.page_param,
            "size_param": pg.size_param,
            "first_page": pg.first_page,
            "total_pages_path": pg.total_pages_path,
            "offset_param": pg.offset_param,
            "limit_param": pg.limit_param,
            "total_path": pg.total_path,
            "cursor_param": pg.cursor_param,
            "next_cursor_path": pg.next_cursor_path,
            "max_pages": pg.max_pages,
        },
        "filter_param_map": dict(cfg.filter_param_map),
        "since_param": cfg.since_param,
        "schema_fields": [
            {
                "name": f.name,
                "type": f.type.value,
                "required": f.required,
                "readonly": f.readonly,
                "label": f.label,
                "choices": list(f.choices) if f.choices is not None else None,
                "relation": f.relation,
            }
            for f in cfg.schema_fields
        ],
    }
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


def resource_config_from_json(text: str) -> ResourceConfig:
    try:
        data = json.loads(text)
    except ValueError:
        raise ResourceConfigInvalid("the stored resource configuration is not valid JSON") from None
    if not isinstance(data, dict):
        raise ResourceConfigInvalid("the resource configuration must be a JSON object")
    if data.get("version") != SCHEMA_VERSION:
        raise ResourceConfigInvalid(
            f"unsupported resource configuration version {data.get('version')!r}"
        )
    endpoints = _mapping(data, "endpoints")
    cfg = ResourceConfig(
        name=_str(data, "name"),
        label=_str(data, "label"),
        list_endpoint=_endpoint(endpoints, "list"),
        get_endpoint=_endpoint(endpoints, "get"),
        create_endpoint=_endpoint(endpoints, "create"),
        update_endpoint=_endpoint(endpoints, "update"),
        items_path=_str(data, "items_path"),
        item_path=_str(data, "item_path"),
        id_field=_str(data, "id_field"),
        pagination=_pagination(_mapping(data, "pagination")),
        filter_param_map=_str_map(_mapping(data, "filter_param_map")),
        since_param=_opt_str(data, "since_param"),
        schema_fields=tuple(_field(item) for item in _list(data, "schema_fields")),
    )
    validate_resource_config(cfg)
    return cfg


def _mapping(data: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ResourceConfigInvalid(f"{key} must be an object")
    return value


def _list(data: Mapping[str, Any], key: str) -> list[Any]:
    value = data.get(key)
    if not isinstance(value, list):
        raise ResourceConfigInvalid(f"{key} must be a list")
    return value


def _str(data: Mapping[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise ResourceConfigInvalid(f"{key} must be a string")
    return value


def _opt_str(data: Mapping[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is not None and not isinstance(value, str):
        raise ResourceConfigInvalid(f"{key} must be a string or null")
    return value


def _int(data: Mapping[str, Any], key: str) -> int:
    value = data.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ResourceConfigInvalid(f"{key} must be an integer")
    return value


def _bool(data: Mapping[str, Any], key: str) -> bool:
    value = data.get(key)
    if not isinstance(value, bool):
        raise ResourceConfigInvalid(f"{key} must be true or false")
    return value


def _str_map(data: Mapping[str, Any]) -> dict[str, str]:
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in data.items()):
        raise ResourceConfigInvalid("filter_param_map must map strings to strings")
    return dict(data)


def _endpoint(endpoints: Mapping[str, Any], operation: str) -> EndpointSpec | None:
    raw = endpoints.get(operation)
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ResourceConfigInvalid(f"endpoints.{operation} must be an object")
    return EndpointSpec(_str(raw, "method"), _str(raw, "path"))


def _strategy(data: Mapping[str, Any], key: str) -> PaginationStrategy:
    try:
        return PaginationStrategy(_str(data, key))
    except ValueError:
        raise ResourceConfigInvalid(f"unknown {key} {data.get(key)!r}") from None


def _field_type(data: Mapping[str, Any], key: str) -> FieldType:
    try:
        return FieldType(_str(data, key))
    except ValueError:
        raise ResourceConfigInvalid(f"unknown {key} {data.get(key)!r}") from None


def _pagination(raw: Mapping[str, Any]) -> PaginationConfig:
    return PaginationConfig(
        strategy=_strategy(raw, "strategy"),
        page_param=_str(raw, "page_param"),
        size_param=_str(raw, "size_param"),
        first_page=_int(raw, "first_page"),
        total_pages_path=_opt_str(raw, "total_pages_path"),
        offset_param=_str(raw, "offset_param"),
        limit_param=_str(raw, "limit_param"),
        total_path=_opt_str(raw, "total_path"),
        cursor_param=_str(raw, "cursor_param"),
        next_cursor_path=_opt_str(raw, "next_cursor_path"),
        max_pages=_int(raw, "max_pages"),
    )


def _field(raw: Any) -> FieldSpec:
    if not isinstance(raw, dict):
        raise ResourceConfigInvalid("schema_fields entries must be objects")
    choices = raw.get("choices")
    if choices is not None and not (
        isinstance(choices, list) and all(isinstance(c, str) for c in choices)
    ):
        raise ResourceConfigInvalid("choices must be a list of strings or null")
    return FieldSpec(
        name=_str(raw, "name"),
        type=_field_type(raw, "type"),
        required=_bool(raw, "required"),
        readonly=_bool(raw, "readonly"),
        label=_opt_str(raw, "label"),
        choices=tuple(choices) if choices is not None else None,
        relation=_opt_str(raw, "relation"),
    )
