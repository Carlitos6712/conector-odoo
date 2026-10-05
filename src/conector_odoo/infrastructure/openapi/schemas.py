"""Read-only helpers over an OpenAPI document: local ``$ref`` resolution and schema flattening.

Everything is bounded (reference chains, ``allOf`` depth) so cyclic or hostile documents degrade
to "unknown schema" instead of recursing forever. Non-local references are never followed.
"""

from typing import Any
from urllib.parse import unquote

from conector_odoo.domain.records import FieldSpec, FieldType

_MAX_REF_CHAIN = 32
_MAX_DEPTH = 8
_ARRAY_NAMES = ("items", "data", "results", "records", "content", "rows", "entries")
_WRAPPER_NAMES = ("data", "item", "result", "record")

_FORMATS = {"date": FieldType.DATE, "date-time": FieldType.DATETIME}
_TYPES = {
    "integer": FieldType.INTEGER,
    "number": FieldType.NUMBER,
    "boolean": FieldType.BOOLEAN,
    "string": FieldType.STRING,
    "object": FieldType.OBJECT,
    "array": FieldType.ARRAY,
}


class SpecReader:
    def __init__(self, document: dict[str, Any]) -> None:
        self._doc = document

    def deref(self, node: Any) -> Any:
        """Follow chained local ``$ref``s; an empty dict for cycles, remote or missing targets."""
        seen: set[str] = set()
        for _ in range(_MAX_REF_CHAIN):
            if not isinstance(node, dict) or "$ref" not in node:
                return node
            ref = node["$ref"]
            if not isinstance(ref, str) or not ref.startswith("#/") or ref in seen:
                return {}
            seen.add(ref)
            node = self._pointer(ref)
        return {}

    def _pointer(self, ref: str) -> Any:
        current: Any = self._doc
        for part in ref[2:].split("/"):
            key = unquote(part).replace("~1", "/").replace("~0", "~")
            if not isinstance(current, dict) or key not in current:
                return {}
            current = current[key]
        return current

    def flatten(self, schema: Any, depth: int = 0) -> dict[str, Any]:
        """One flat view of a schema: resolves ``$ref``, merges ``allOf`` and picks the first
        non-null ``anyOf``/``oneOf`` branch. Keys: type, properties, required, items, format,
        enum, title, readOnly (only those present)."""
        node = self.deref(schema)
        if not isinstance(node, dict) or depth > _MAX_DEPTH:
            return {}
        merged: dict[str, Any] = {}
        for branch in node.get("allOf") or []:
            _merge(merged, self.flatten(branch, depth + 1))
        for key in ("anyOf", "oneOf"):
            options = [self.flatten(b, depth + 1) for b in node.get(key) or []]
            options = [o for o in options if o and o.get("type") != "null"]
            if options:
                _merge(merged, options[0])
        own = {k: v for k, v in node.items() if k not in ("allOf", "anyOf", "oneOf")}
        _merge(merged, own)
        return merged

    def response_schema(self, operation: dict[str, Any]) -> Any:
        """Schema of the first 2xx response (OpenAPI 3 ``content`` or Swagger 2 ``schema``)."""
        responses = operation.get("responses")
        if not isinstance(responses, dict):
            return {}
        for code in sorted(responses, key=str):
            if not str(code).startswith("2"):
                continue
            response = self.deref(responses[code])
            if not isinstance(response, dict):
                continue
            content = response.get("content")
            if isinstance(content, dict) and content:
                media = next((m for m in content if "json" in m), next(iter(content)))
                entry = self.deref(content[media])
                return entry.get("schema", {}) if isinstance(entry, dict) else {}
            if "schema" in response:
                return response["schema"]
        return {}

    def parameters(self, *sources: dict[str, Any]) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        for source in sources:
            for raw in source.get("parameters") or []:
                param = self.deref(raw)
                if isinstance(param, dict) and param.get("name"):
                    found.append(param)
        return found

    def list_shape(self, schema: Any) -> tuple[str, dict[str, Any], dict[str, Any]] | None:
        """``(items_path, item_schema, root_properties)`` of a list response, or ``None``."""
        flat = self.flatten(schema)
        if flat.get("type") == "array" or "items" in flat:
            return "", self.flatten(flat.get("items", {})), {}
        props = flat.get("properties")
        if not isinstance(props, dict):
            return None
        arrays = {n: self.flatten(p) for n, p in props.items()}
        arrays = {n: f for n, f in arrays.items() if f.get("type") == "array" or "items" in f}
        if not arrays:
            return None
        name = next((n for n in _ARRAY_NAMES if n in arrays), next(iter(arrays)))
        return name, self.flatten(arrays[name].get("items", {})), dict(props)

    def item_shape(self, schema: Any) -> tuple[str, dict[str, Any]]:
        """``(item_path, item_schema)`` of a single-record response (unwraps ``data`` & co)."""
        flat = self.flatten(schema)
        props = flat.get("properties")
        if isinstance(props, dict) and not any(n in props for n in ("id", "uuid")):
            for name in _WRAPPER_NAMES:
                inner = self.flatten(props.get(name, {}))
                if isinstance(inner.get("properties"), dict):
                    return name, inner
        return "", flat

    def fields(self, item_schema: dict[str, Any]) -> tuple[FieldSpec, ...]:
        props = item_schema.get("properties")
        if not isinstance(props, dict):
            return ()
        required = set(item_schema.get("required") or [])
        specs: list[FieldSpec] = []
        for name, raw in props.items():
            flat = self.flatten(raw)
            enum = flat.get("enum")
            specs.append(
                FieldSpec(
                    name=str(name),
                    type=_field_type(flat),
                    required=name in required,
                    readonly=bool(flat.get("readOnly")),
                    label=flat.get("title") if isinstance(flat.get("title"), str) else None,
                    choices=(
                        tuple(str(v) for v in enum)
                        if isinstance(enum, list) and enum and flat.get("type") != "array"
                        else None
                    ),
                )
            )
        return tuple(specs)


def _merge(target: dict[str, Any], part: dict[str, Any]) -> None:
    for key, value in part.items():
        if key == "properties" and isinstance(value, dict):
            target.setdefault("properties", {}).update(value)
        elif key == "required" and isinstance(value, list):
            target["required"] = [*target.get("required", []), *value]
        else:
            target.setdefault(key, value)


def _field_type(flat: dict[str, Any]) -> FieldType:
    kind = flat.get("type")
    if isinstance(kind, list):
        kind = next((k for k in kind if k != "null"), None)
    if kind == "string" and flat.get("format") in _FORMATS:
        return _FORMATS[flat["format"]]
    if kind in _TYPES:
        return _TYPES[kind]
    if "properties" in flat:
        return FieldType.OBJECT
    if "items" in flat:
        return FieldType.ARRAY
    return FieldType.UNKNOWN
