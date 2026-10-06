from typing import Any

from conector_odoo.domain.mapping import (
    Constant,
    Direct,
    Severity,
    ToCents,
    ToInt,
)
from conector_odoo.domain.mapping_validation import dry_run
from conector_odoo.domain.records import FieldSpec, FieldType, ResourceSchema
from tests.mapping.helpers import definition, rec, rule, steps

TARGET = ResourceSchema(
    name="partner",
    label="Partner",
    fields=(
        FieldSpec("name", FieldType.STRING, required=True),
        FieldSpec("age", FieldType.INTEGER),
        FieldSpec("score", FieldType.NUMBER),
        FieldSpec("active", FieldType.BOOLEAN),
        FieldSpec("born", FieldType.DATE),
        FieldSpec("seen", FieldType.DATETIME),
        FieldSpec("kind", FieldType.STRING, choices=("a", "b")),
        FieldSpec("address", FieldType.OBJECT),
    ),
)


def mapped(**sources: Any) -> Any:
    rules = tuple(rule(target, Direct(target)) for target in sources)
    return dry_run(definition(*rules), [rec(**sources)], TARGET)


def test_clean_record_is_ok_and_summary_counts() -> None:
    d = definition(rule("name", Direct("n")), rule("age", steps(Direct("a"), ToInt())))
    report = dry_run(
        d, [rec("1", n="Ana", a="3"), rec("2", n="Bo", a="x"), rec(None, a="1")], TARGET
    )
    assert [i.source_id for i in report.items] == ["1", "2", None]
    assert report.items[0].mapped_fields == {"name": "Ana", "age": 3}
    assert report.items[0].errors == [] and report.items[0].validation == []
    assert (report.summary.total, report.summary.ok, report.summary.with_errors) == (3, 1, 2)


def test_rule_errors_and_missing_required_field_are_reported() -> None:
    d = definition(rule("age", steps(Direct("a"), ToInt())))
    item = dry_run(d, [rec("1", a="x")], TARGET).items[0]
    assert [e.rule_target for e in item.errors] == ["age"]
    assert [(v.path, v.severity) for v in item.validation] == [("name", Severity.ERROR)]
    assert "required" in item.validation[0].message


def test_value_type_checks_per_field() -> None:
    bad = mapped(age="3", score="1.5", active="yes", born="05/03/2024", seen="nope", name=7)
    assert {v.path for v in bad.items[0].validation} == {
        "age",
        "score",
        "active",
        "born",
        "seen",
        "name",
    }
    assert all(v.severity is Severity.ERROR for v in bad.items[0].validation)


def test_valid_values_pass_type_checks() -> None:
    good = mapped(
        name="n",
        age=3,
        score=2,
        active=False,
        born="2024-03-05",
        seen="2024-03-05T10:00:00+00:00",
        kind="a",
        address={"city": "x"},
    )
    assert good.items[0].validation == []


def test_bool_is_not_an_integer_or_number() -> None:
    report = mapped(name="n", age=True, score=False)
    assert {v.path for v in report.items[0].validation} == {"age", "score"}


def test_choices_membership() -> None:
    report = mapped(name="n", kind="zzz")
    issue = report.items[0].validation[0]
    assert issue.path == "kind"
    assert "a, b" in issue.message


def test_float_into_integer_field_is_flagged_and_money_in_cents_is_fine() -> None:
    d = definition(rule("name", Constant("n")), rule("age", steps(Direct("m"), ToCents())))
    assert dry_run(d, [rec(m="12.34")], TARGET).items[0].validation == []
    d2 = definition(rule("name", Constant("n")), rule("age", Constant(1.5)))
    assert [v.path for v in dry_run(d2, [rec()], TARGET).items[0].validation] == ["age"]


def test_nested_targets_check_the_root_field_only() -> None:
    d = definition(rule("name", Constant("n")), rule("address.city", Constant("x")))
    assert dry_run(d, [rec()], TARGET).items[0].validation == []


def test_definition_issues_use_both_schemas() -> None:
    src = ResourceSchema("s", "S", (FieldSpec("n", FieldType.STRING),))
    d = definition(rule("ghost", Direct("zz")))
    report = dry_run(d, [], TARGET, src)
    assert {(i.path, i.severity) for i in report.definition_issues} == {
        ("rules[0].expr.source", Severity.WARNING),
        ("rules[0].target", Severity.ERROR),
        ("target.name", Severity.ERROR),
    }
    assert report.summary.total == 0


def test_dry_run_never_raises_on_odd_data() -> None:
    d = definition(rule("name", steps(Direct("a"), ToInt())))
    report = dry_run(d, [rec(a=[1, 2]), rec(a={"x": 1}), rec()], TARGET)
    assert report.summary.with_errors == 3
