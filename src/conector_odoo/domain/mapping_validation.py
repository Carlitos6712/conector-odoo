"""Static validation of a mapping against optional schemas, and dry-run reports.

Pure domain: stdlib only. ``validate_definition`` never raises; it returns every finding so the
editor can show them all. ``dry_run`` runs the engine over sample records and also checks the
mapped values against the target field types.
"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from conector_odoo.domain.mapping import (
    Coalesce,
    Concat,
    Constant,
    DateFormat,
    Default,
    Direct,
    Expr,
    FromCents,
    Lookup,
    MappingDefinition,
    MappingRule,
    RuleError,
    Severity,
    Step,
    ToBool,
    ToCents,
    ToInt,
    ToNumber,
    Transform,
    ValidationIssue,
)
from conector_odoo.domain.mapping_engine import apply_mapping
from conector_odoo.domain.records import FieldSpec, FieldType, Record, ResourceSchema

_FITS = {
    (FieldType.INTEGER, FieldType.NUMBER),
    (FieldType.STRING, FieldType.DATE),
    (FieldType.STRING, FieldType.DATETIME),
    (FieldType.DATE, FieldType.DATETIME),
}
_UNCHECKED_TARGETS = {FieldType.UNKNOWN, FieldType.OBJECT, FieldType.ARRAY}


def _error(path: str, message: str) -> ValidationIssue:
    return ValidationIssue(path, Severity.ERROR, message)


def _warning(path: str, message: str) -> ValidationIssue:
    return ValidationIssue(path, Severity.WARNING, message)


def validate_definition(
    definition: MappingDefinition,
    source_schema: ResourceSchema | None,
    target_schema: ResourceSchema | None,
) -> list[ValidationIssue]:
    found: list[ValidationIssue] = []
    for attribute in ("name", "source_resource", "target_resource"):
        if not getattr(definition, attribute).strip():
            found.append(_error(attribute, f"{attribute} must not be empty"))
    if not definition.rules:
        found.append(_error("rules", "a mapping needs at least one rule"))
    seen: list[str] = []
    for index, rule in enumerate(definition.rules):
        path = f"rules[{index}]"
        found.extend(_check_target(rule.target, seen, f"{path}.target"))
        seen.append(rule.target)
        if target_schema is not None:
            found.extend(_check_against_target(rule, target_schema, f"{path}.target"))
        for node_path, node in _walk(rule.expr, f"{path}.expr"):
            found.extend(_check_node(node, node_path, source_schema))
        if target_schema is not None:
            found.extend(_check_types(rule, source_schema, target_schema, f"{path}.target"))
    if target_schema is not None:
        found.extend(_check_required(definition.rules, target_schema))
    return found


def _check_target(target: str, earlier: list[str], path: str) -> list[ValidationIssue]:
    parts = target.split(".")
    if any(not part or part != part.strip() for part in parts):
        return [_error(path, f"invalid target {target!r}: use names separated by single dots")]
    for other in earlier:
        if other == target:
            return [_error(path, f"duplicate target {target!r}")]
        if other.startswith(target + ".") or target.startswith(other + "."):
            return [_error(path, f"target {target!r} conflicts with {other!r}")]
    return []


def _check_against_target(
    rule: MappingRule, schema: ResourceSchema, path: str
) -> list[ValidationIssue]:
    root = rule.target.split(".")[0]
    spec = schema.field(root)
    if spec is None:
        return [_error(path, f"target field {root!r} does not exist in {schema.name!r}")]
    if spec.readonly:
        return [_warning(path, f"target field {root!r} is read-only; the remote may ignore it")]
    return []


def _check_required(rules: Sequence[MappingRule], schema: ResourceSchema) -> list[ValidationIssue]:
    covered = {rule.target.split(".")[0] for rule in rules}
    return [
        _error(f"target.{spec.name}", f"required target field {spec.name!r} has no rule")
        for spec in schema.fields
        if spec.required and not spec.readonly and spec.name not in covered
    ]


def _walk(expr: Expr, path: str) -> Iterator[tuple[str, Expr | Step]]:
    yield path, expr
    if isinstance(expr, Concat):
        for index, part in enumerate(expr.parts):
            yield from _walk(part, f"{path}.parts[{index}]")
    elif isinstance(expr, Transform):
        yield from _walk(expr.input, f"{path}.input")
        for index, step in enumerate(expr.steps):
            step_path = f"{path}.steps[{index}]"
            yield step_path, step
            if isinstance(step, Coalesce):
                for position, alternative in enumerate(step.alternatives):
                    yield from _walk(alternative, f"{step_path}.alternatives[{position}]")


def _check_node(
    node: Expr | Step, path: str, source_schema: ResourceSchema | None
) -> list[ValidationIssue]:
    if isinstance(node, Direct):
        root = node.source.split(".")[0]
        if source_schema is not None and source_schema.field(root) is None:
            return [_warning(f"{path}.source", f"source field {root!r} is not in the schema")]
    elif isinstance(node, Lookup) and not node.table:
        return [_warning(f"{path}.table", "the lookup table is empty")]
    elif isinstance(node, ToCents | FromCents) and node.factor < 1:
        return [_error(f"{path}.factor", "factor must be a positive integer")]
    elif isinstance(node, DateFormat):
        return [
            _error(f"{path}.{name}", f"{name} must not be empty")
            for name in ("in_format", "out_format")
            if not getattr(node, name).strip()
        ]
    return []


def _check_types(
    rule: MappingRule,
    source_schema: ResourceSchema | None,
    schema: ResourceSchema,
    path: str,
) -> list[ValidationIssue]:
    if "." in rule.target:
        return []
    spec = schema.field(rule.target)
    produced = _output_type(rule.expr, source_schema)
    if spec is None or spec.type in _UNCHECKED_TARGETS or produced is None:
        return []
    if produced is spec.type or (produced, spec.type) in _FITS:
        return []
    return [
        _warning(path, f"the rule produces {produced.value} but {spec.name!r} is {spec.type.value}")
    ]


def _output_type(expr: Expr, source_schema: ResourceSchema | None) -> FieldType | None:
    match expr:
        case Direct(source=source):
            spec = source_schema.field(source) if source_schema is not None else None
            return None if spec is None or spec.type is FieldType.UNKNOWN else spec.type
        case Constant(value=value):
            return _constant_type(value)
        case Concat():
            return FieldType.STRING
        case Transform(input=inner, steps=chain):
            for step in reversed(chain):
                if isinstance(step, Default | Coalesce):
                    continue
                return _step_type(step)
            return _output_type(inner, source_schema)
    return None


def _constant_type(value: Any) -> FieldType | None:
    if isinstance(value, bool):
        return FieldType.BOOLEAN
    for python, field_type in (
        (int, FieldType.INTEGER),
        (float, FieldType.NUMBER),
        (str, FieldType.STRING),
        (dict, FieldType.OBJECT),
        (list, FieldType.ARRAY),
    ):
        if isinstance(value, python):
            return field_type
    return None


def _step_type(step: Step) -> FieldType | None:
    match step:
        case ToNumber():
            return FieldType.NUMBER
        case ToInt() | ToCents():
            return FieldType.INTEGER
        case ToBool():
            return FieldType.BOOLEAN
        case FromCents(as_string=as_string):
            return FieldType.STRING if as_string else FieldType.NUMBER
        case Lookup():
            return None
    return FieldType.STRING  # trim, case, replace, substring, to_string, date_format


# -- dry run -----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DryRunItem:
    source_id: str | None
    mapped_fields: dict[str, Any]
    errors: list[RuleError]
    validation: list[ValidationIssue]

    @property
    def ok(self) -> bool:
        return not self.errors and all(v.severity is not Severity.ERROR for v in self.validation)


@dataclass(frozen=True, slots=True)
class DryRunSummary:
    total: int
    ok: int
    with_errors: int


@dataclass(frozen=True, slots=True)
class DryRunReport:
    items: list[DryRunItem]
    summary: DryRunSummary
    definition_issues: list[ValidationIssue]


def dry_run(
    definition: MappingDefinition,
    source_records: Sequence[Record],
    target_schema: ResourceSchema,
    source_schema: ResourceSchema | None = None,
) -> DryRunReport:
    """Map every sample record without writing anything and check the values against the target
    field types. Never raises for data problems."""
    items = []
    for record in source_records:
        result = apply_mapping(definition, record)
        items.append(
            DryRunItem(
                record.id, result.fields, result.errors, _check_values(result.fields, target_schema)
            )
        )
    ok = sum(1 for item in items if item.ok)
    return DryRunReport(
        items,
        DryRunSummary(total=len(items), ok=ok, with_errors=len(items) - ok),
        validate_definition(definition, source_schema, target_schema),
    )


def _check_values(fields: dict[str, Any], schema: ResourceSchema) -> list[ValidationIssue]:
    found: list[ValidationIssue] = []
    for spec in schema.fields:
        if spec.name not in fields:
            if spec.required and not spec.readonly:
                found.append(_error(spec.name, "required field has no value"))
            continue
        problem = _value_problem(spec, fields[spec.name])
        if problem:
            found.append(_error(spec.name, problem))
    return found


def _value_problem(spec: FieldSpec, value: Any) -> str | None:
    expected = spec.type
    if not _has_type(expected, value):
        return f"expected {expected.value}, got {value!r}"
    if spec.choices and value not in spec.choices:
        return f"{value!r} is not one of: {', '.join(spec.choices)}"
    return None


def _has_type(expected: FieldType, value: Any) -> bool:
    match expected:
        case FieldType.INTEGER:
            return isinstance(value, int) and not isinstance(value, bool)
        case FieldType.NUMBER:
            return isinstance(value, int | float | Decimal) and not isinstance(value, bool)
        case FieldType.BOOLEAN:
            return isinstance(value, bool)
        case FieldType.STRING:
            return isinstance(value, str)
        case FieldType.DATE:
            return isinstance(value, date) or _parses(date.fromisoformat, value)
        case FieldType.DATETIME:
            return isinstance(value, datetime) or _parses(datetime.fromisoformat, value)
        case FieldType.OBJECT:
            return isinstance(value, dict)
        case FieldType.ARRAY:
            return isinstance(value, list)
    return True


def _parses(parser: Any, value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parser(value)
    except ValueError:
        return False
    return True
