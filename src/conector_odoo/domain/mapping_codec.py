"""Versioned JSON (de)serialisation of ``MappingDefinition``.

Pure domain: stdlib only. Every expression and step carries a ``type`` discriminator. Anything
unknown or malformed raises ``MappingInvalid`` with a message that starts with the offending path
(``rules[2].expr.steps[1]: ...``) so the editor can point at it.
"""

import json
from dataclasses import MISSING, fields
from typing import Any

from conector_odoo.domain.errors import MappingInvalid
from conector_odoo.domain.mapping import (
    SCHEMA_VERSION,
    Coalesce,
    Concat,
    Constant,
    DateFormat,
    Default,
    Direct,
    Expr,
    FromCents,
    Lookup,
    LookupMissing,
    Lower,
    MappingDefinition,
    MappingRule,
    Replace,
    Step,
    Substring,
    Title,
    ToBool,
    ToCents,
    ToInt,
    ToNumber,
    ToString,
    Transform,
    Trim,
    Upper,
)

# field kind: str, int, optint, bool, any, table, lookup_missing, expr, exprs, steps
_EXPRESSIONS: dict[str, tuple[type, dict[str, str]]] = {
    "direct": (Direct, {"source": "str", "default": "any"}),
    "constant": (Constant, {"value": "any"}),
    "concat": (Concat, {"parts": "exprs", "separator": "str", "skip_empty": "bool"}),
    "transform": (Transform, {"input": "expr", "steps": "steps"}),
}
_STEPS: dict[str, tuple[type, dict[str, str]]] = {
    "trim": (Trim, {}),
    "upper": (Upper, {}),
    "lower": (Lower, {}),
    "title": (Title, {}),
    "to_string": (ToString, {}),
    "to_number": (ToNumber, {}),
    "to_int": (ToInt, {}),
    "to_bool": (ToBool, {}),
    "replace": (Replace, {"old": "str", "new": "str"}),
    "default": (Default, {"value": "any"}),
    "date_format": (DateFormat, {"in_format": "str", "out_format": "str"}),
    "to_cents": (ToCents, {"factor": "int"}),
    "from_cents": (FromCents, {"factor": "int", "as_string": "bool"}),
    "lookup": (Lookup, {"table": "table", "on_missing": "lookup_missing", "default": "any"}),
    "coalesce": (Coalesce, {"alternatives": "exprs"}),
    "substring": (Substring, {"start": "int", "end": "optint"}),
}
_NAME_OF: dict[type, str] = {cls: name for name, (cls, _) in {**_EXPRESSIONS, **_STEPS}.items()}


# -- encode ------------------------------------------------------------------------------------


def mapping_to_dict(definition: MappingDefinition) -> dict[str, Any]:
    return {
        "schema_version": definition.schema_version,
        "name": definition.name,
        "source_resource": definition.source_resource,
        "target_resource": definition.target_resource,
        "rules": [
            {"target": r.target, "expr": _encode(r.expr), "required": r.required}
            for r in definition.rules
        ],
    }


def mapping_to_json(definition: MappingDefinition) -> str:
    try:
        return json.dumps(mapping_to_dict(definition), ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise MappingInvalid(
            f"mapping {definition.name!r} is not JSON-serialisable: {exc}"
        ) from exc


def _encode(node: Any) -> Any:
    if isinstance(node, tuple):
        return [_encode(item) for item in node]
    name = _NAME_OF.get(type(node))
    if name is None:
        return node.value if isinstance(node, LookupMissing) else node
    doc: dict[str, Any] = {"type": name}
    for spec in fields(node):
        doc[spec.name] = _encode(getattr(node, spec.name))
    if isinstance(node, Lookup):
        doc["table"] = dict(node.table)
    return doc


# -- decode ------------------------------------------------------------------------------------


def mapping_from_json(text: str) -> MappingDefinition:
    try:
        doc = json.loads(text)
    except ValueError as exc:
        raise MappingInvalid(f"mapping is not valid JSON: {exc}") from exc
    return mapping_from_dict(doc)


def mapping_from_dict(doc: Any) -> MappingDefinition:
    obj = _object(doc, "mapping")
    version = obj.get("schema_version", SCHEMA_VERSION)
    if version != SCHEMA_VERSION or isinstance(version, bool):
        raise MappingInvalid(f"schema_version: unsupported version {version!r}")
    rules_doc = obj.get("rules")
    if not isinstance(rules_doc, list):
        raise MappingInvalid("rules: expected a list")
    rules = tuple(_rule(item, f"rules[{i}]") for i, item in enumerate(rules_doc))
    return MappingDefinition(
        name=_text(obj, "name"),
        source_resource=_text(obj, "source_resource"),
        target_resource=_text(obj, "target_resource"),
        rules=rules,
        schema_version=SCHEMA_VERSION,
    )


def _object(doc: Any, path: str) -> dict[str, Any]:
    if not isinstance(doc, dict):
        raise MappingInvalid(f"{path}: expected an object")
    return doc


def _text(obj: dict[str, Any], key: str) -> str:
    if key not in obj:
        raise MappingInvalid(f"missing {key!r}")
    value = obj[key]
    if not isinstance(value, str):
        raise MappingInvalid(f"{key}: expected text")
    return value


def _rule(doc: Any, path: str) -> MappingRule:
    obj = _object(doc, path)
    for key in ("target", "expr"):
        if key not in obj:
            raise MappingInvalid(f"{path}: missing {key!r}")
    target = obj["target"]
    if not isinstance(target, str):
        raise MappingInvalid(f"{path}.target: expected text")
    required = obj.get("required", False)
    if not isinstance(required, bool):
        raise MappingInvalid(f"{path}.required: expected true or false")
    return MappingRule(target, _expr(obj["expr"], f"{path}.expr"), required)


def _expr(doc: Any, path: str) -> Expr:
    node = _node(doc, path, _EXPRESSIONS, "expression")
    assert isinstance(node, Direct | Constant | Concat | Transform)
    return node


def _step(doc: Any, path: str) -> Step:
    node = _node(doc, path, _STEPS, "step")
    return node  # type: ignore[no-any-return]


def _node(doc: Any, path: str, registry: dict[str, tuple[type, dict[str, str]]], noun: str) -> Any:
    obj = _object(doc, path)
    if "type" not in obj:
        raise MappingInvalid(f"{path}: missing 'type'")
    entry = registry.get(obj["type"]) if isinstance(obj["type"], str) else None
    if entry is None:
        raise MappingInvalid(f"{path}: unknown {noun} type {obj['type']!r}")
    cls, kinds = entry
    for key in obj:
        if key != "type" and key not in kinds:
            raise MappingInvalid(f"{path}: unknown field {key!r}")
    values: dict[str, Any] = {}
    for spec in fields(cls):
        if spec.name not in obj:
            if spec.default is MISSING and spec.default_factory is MISSING:
                raise MappingInvalid(f"{path}: missing {spec.name!r}")
            continue
        values[spec.name] = _value(obj[spec.name], kinds[spec.name], f"{path}.{spec.name}")
    return cls(**values)


def _value(value: Any, kind: str, path: str) -> Any:
    match kind:
        case "any":
            return value
        case "str" if isinstance(value, str):
            return value
        case "str":
            raise MappingInvalid(f"{path}: expected text")
        case "bool" if isinstance(value, bool):
            return value
        case "bool":
            raise MappingInvalid(f"{path}: expected true or false")
        case "int" | "optint" if isinstance(value, int) and not isinstance(value, bool):
            return value
        case "optint" if value is None:
            return None
        case "int" | "optint":
            raise MappingInvalid(f"{path}: expected an integer")
        case "table":
            if not isinstance(value, dict):
                raise MappingInvalid(f"{path}: expected an object")
            return dict(value)
        case "lookup_missing":
            try:
                return LookupMissing(value)
            except ValueError:
                allowed = ", ".join(m.value for m in LookupMissing)
                raise MappingInvalid(f"{path}: expected one of {allowed}") from None
        case "expr":
            return _expr(value, path)
        case _:
            return _sequence(value, kind, path)


def _sequence(value: Any, kind: str, path: str) -> tuple[Any, ...]:
    if not isinstance(value, list):
        raise MappingInvalid(f"{path}: expected a list")
    build = _step if kind == "steps" else _expr
    return tuple(build(item, f"{path}[{i}]") for i, item in enumerate(value))
