from typing import Any

from conector_odoo.domain.mapping import (
    Coalesce,
    Concat,
    Constant,
    DateFormat,
    Direct,
    FromCents,
    Lookup,
    MappingDefinition,
    Severity,
    ToCents,
    ToInt,
    ToNumber,
    ToString,
    Trim,
    ValidationIssue,
)
from conector_odoo.domain.mapping_validation import validate_definition
from conector_odoo.domain.records import FieldSpec, FieldType, ResourceSchema
from tests.mapping.helpers import definition, rule, steps


def schema(*fields: FieldSpec) -> ResourceSchema:
    return ResourceSchema(name="r", label="R", fields=fields)


def issues(d: MappingDefinition, src: Any = None, dst: Any = None) -> list[ValidationIssue]:
    return validate_definition(d, src, dst)


def find(found: list[ValidationIssue], severity: Severity, fragment: str) -> ValidationIssue:
    matches = [i for i in found if i.severity is severity and fragment in i.message]
    assert matches, f"no {severity} containing {fragment!r} in {found}"
    return matches[0]


def test_valid_definition_without_schemas_has_no_issues() -> None:
    assert issues(definition(rule("a", Direct("x")))) == []


def test_empty_names_and_no_rules_are_errors() -> None:
    d = MappingDefinition(name=" ", source_resource="", target_resource="t", rules=())
    found = issues(d)
    assert {i.path for i in found if i.severity is Severity.ERROR} == {
        "name",
        "source_resource",
        "rules",
    }


def test_bad_target_syntax() -> None:
    for target in ("", "a..b", ".a", "a.", " "):
        found = issues(definition(rule(target, Constant(1))))
        assert find(found, Severity.ERROR, "target").path == "rules[0].target"


def test_duplicate_targets() -> None:
    found = issues(definition(rule("a", Constant(1)), rule("a", Constant(2))))
    assert find(found, Severity.ERROR, "duplicate").path == "rules[1].target"


def test_conflicting_nested_targets() -> None:
    found = issues(definition(rule("a.b", Constant(1)), rule("a", Constant(2))))
    assert find(found, Severity.ERROR, "conflicts").path == "rules[1].target"
    found = issues(definition(rule("a", Constant(2)), rule("a.b.c", Constant(1))))
    assert find(found, Severity.ERROR, "conflicts").path == "rules[1].target"


def test_sibling_nested_targets_are_fine() -> None:
    assert issues(definition(rule("a.b", Constant(1)), rule("a.c", Constant(2)))) == []


def test_unknown_source_field_is_a_warning_only_when_schema_known() -> None:
    d = definition(rule("a", Direct("nope")), rule("b", Direct("known.deep")))
    src = schema(FieldSpec("known", FieldType.OBJECT))
    found = issues(d, src)
    assert [i.path for i in found] == ["rules[0].expr.source"]
    assert found[0].severity is Severity.WARNING
    assert issues(d) == []


def test_unknown_source_inside_nested_expressions() -> None:
    d = definition(
        rule("a", Concat((Direct("p"), steps(Direct("q"), Trim(), Coalesce((Direct("r"),)))))),
    )
    found = issues(d, schema(FieldSpec("p", FieldType.STRING)))
    assert sorted(i.path for i in found) == [
        "rules[0].expr.parts[1].input.source",
        "rules[0].expr.parts[1].steps[1].alternatives[0].source",
    ]


def test_unknown_target_field_is_an_error_when_schema_known() -> None:
    found = issues(
        definition(rule("zzz", Constant(1)), rule("addr.city", Constant(1))),
        dst=schema(FieldSpec("addr", FieldType.OBJECT)),
    )
    assert [(i.path, i.severity) for i in found] == [("rules[0].target", Severity.ERROR)]


def test_required_target_fields_not_covered() -> None:
    dst = schema(
        FieldSpec("name", FieldType.STRING, required=True),
        FieldSpec("addr", FieldType.OBJECT, required=True),
        FieldSpec("id", FieldType.STRING, required=True, readonly=True),
        FieldSpec("note", FieldType.STRING),
    )
    found = issues(definition(rule("addr.city", Constant("x"))), dst=dst)
    assert [(i.path, i.severity) for i in found] == [("target.name", Severity.ERROR)]


def test_readonly_target_mapped_is_a_warning() -> None:
    dst = schema(FieldSpec("id", FieldType.STRING, readonly=True))
    found = issues(definition(rule("id", Constant("1"))), dst=dst)
    assert [(i.path, i.severity) for i in found] == [("rules[0].target", Severity.WARNING)]


def test_type_mismatch_heuristics() -> None:
    dst = schema(
        FieldSpec("s", FieldType.STRING),
        FieldSpec("n", FieldType.NUMBER),
        FieldSpec("i", FieldType.INTEGER),
        FieldSpec("b", FieldType.BOOLEAN),
        FieldSpec("d", FieldType.DATE),
        FieldSpec("o", FieldType.OBJECT),
    )
    d = definition(
        rule("s", steps(Direct("x"), ToNumber())),  # number into string
        rule("n", steps(Direct("x"), ToString())),  # string into number
        rule("i", steps(Direct("x"), ToCents())),  # integer into integer: fine
        rule("b", Constant("yes")),  # string constant into boolean
        rule("d", steps(Direct("x"), DateFormat("iso", "%Y-%m-%d"))),  # string into date: fine
        rule("o", steps(Direct("x"), ToNumber())),  # object/array/unknown targets are not checked
    )
    found = issues(d, dst=dst)
    assert [(i.path, i.severity) for i in found] == [
        ("rules[0].target", Severity.WARNING),
        ("rules[1].target", Severity.WARNING),
        ("rules[3].target", Severity.WARNING),
    ]


def test_integer_into_number_field_and_default_steps_keep_the_type() -> None:
    dst = schema(FieldSpec("n", FieldType.NUMBER), FieldSpec("s", FieldType.STRING))
    d = definition(
        rule("n", steps(Direct("x"), ToInt())),
        rule("s", steps(Direct("x"), FromCents())),
    )
    assert issues(d, dst=dst) == []


def test_direct_type_comes_from_the_source_schema() -> None:
    src = schema(FieldSpec("age", FieldType.INTEGER))
    dst = schema(FieldSpec("age", FieldType.STRING))
    found = issues(definition(rule("age", Direct("age"))), src, dst)
    assert [i.severity for i in found] == [Severity.WARNING]


def test_empty_lookup_table_is_a_warning() -> None:
    found = issues(definition(rule("a", steps(Direct("x"), Trim(), Lookup({})))))
    assert [(i.path, i.severity) for i in found] == [
        ("rules[0].expr.steps[1].table", Severity.WARNING)
    ]


def test_invalid_step_parameters() -> None:
    d = definition(
        rule("a", steps(Direct("x"), ToCents(0))),
        rule("b", steps(Direct("x"), FromCents(-5))),
        rule("c", steps(Direct("x"), DateFormat("", "iso"))),
    )
    assert [(i.path, i.severity) for i in issues(d)] == [
        ("rules[0].expr.steps[0].factor", Severity.ERROR),
        ("rules[1].expr.steps[0].factor", Severity.ERROR),
        ("rules[2].expr.steps[0].in_format", Severity.ERROR),
    ]
