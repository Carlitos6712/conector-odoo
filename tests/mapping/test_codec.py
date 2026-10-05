import json
from typing import Any

import pytest

from conector_odoo.domain.errors import MappingInvalid
from conector_odoo.domain.mapping import (
    Coalesce,
    Concat,
    Constant,
    DateFormat,
    Default,
    Direct,
    FromCents,
    Lookup,
    LookupMissing,
    Lower,
    Replace,
    Substring,
    Title,
    ToBool,
    ToCents,
    ToInt,
    ToNumber,
    ToString,
    Trim,
    Upper,
)
from conector_odoo.domain.mapping_codec import (
    mapping_from_dict,
    mapping_from_json,
    mapping_to_dict,
    mapping_to_json,
)
from tests.mapping.helpers import definition, rule, steps

EVERY_STEP = (
    Trim(),
    Upper(),
    Lower(),
    Title(),
    ToString(),
    ToNumber(),
    ToInt(),
    ToBool(),
    Replace("a", "b"),
    Default("x"),
    DateFormat("%d/%m/%Y", "epoch"),
    ToCents(1000),
    FromCents(10, as_string=False),
    Lookup({"a": 1}, LookupMissing.DEFAULT, "d"),
    Coalesce((Direct("p"), Constant(3))),
    Substring(1, None),
)


def full_definition() -> Any:
    return definition(
        rule("a", Direct("x.y", default=0), required=True),
        rule("b.c", Constant([1, {"k": None}])),
        rule("d", Concat((Direct("p"), Constant("-")), separator=" ", skip_empty=False)),
        rule("e", steps(Direct("q"), *EVERY_STEP)),
    )


def test_round_trip_every_expression_and_step() -> None:
    original = full_definition()
    assert mapping_from_json(mapping_to_json(original)) == original
    assert mapping_from_dict(mapping_to_dict(original)) == original


def test_json_carries_type_discriminators_and_schema_version() -> None:
    doc = json.loads(mapping_to_json(definition(rule("a", steps(Direct("x"), Trim())))))
    assert doc["schema_version"] == 1
    expr = doc["rules"][0]["expr"]
    assert expr["type"] == "transform"
    assert expr["input"] == {"type": "direct", "source": "x", "default": None}
    assert expr["steps"] == [{"type": "trim"}]


def test_optional_fields_take_defaults() -> None:
    doc = {
        "name": "m",
        "source_resource": "s",
        "target_resource": "t",
        "schema_version": 1,
        "rules": [{"target": "a", "expr": {"type": "direct", "source": "x"}}],
    }
    parsed = mapping_from_dict(doc)
    assert parsed.rules[0].required is False
    assert parsed.rules[0].expr == Direct("x")


def doc_with_expr(expr: Any) -> dict[str, Any]:
    return {
        "name": "m",
        "source_resource": "s",
        "target_resource": "t",
        "schema_version": 1,
        "rules": [{"target": "a", "expr": expr}],
    }


@pytest.mark.parametrize(
    ("expr", "fragment"),
    [
        ({"type": "magic"}, "rules[0].expr: unknown expression type 'magic'"),
        ({"source": "x"}, "rules[0].expr: missing 'type'"),
        (
            {
                "type": "transform",
                "input": {"type": "direct", "source": "x"},
                "steps": [{"type": "x"}],
            },
            "rules[0].expr.steps[0]: unknown step type 'x'",
        ),
        (
            {"type": "concat", "parts": [{"type": "direct", "source": "a"}, {"type": "zzz"}]},
            "rules[0].expr.parts[1]: unknown expression type 'zzz'",
        ),
        ({"type": "direct"}, "rules[0].expr: missing 'source'"),
        ({"type": "direct", "source": 5}, "rules[0].expr.source: expected text"),
        ({"type": "direct", "source": "x", "bogus": 1}, "rules[0].expr: unknown field 'bogus'"),
        (
            {
                "type": "transform",
                "input": {"type": "constant", "value": 1},
                "steps": [{"type": "to_cents", "factor": "x"}],
            },
            "rules[0].expr.steps[0].factor: expected an integer",
        ),
        (
            {
                "type": "transform",
                "input": {"type": "constant", "value": 1},
                "steps": [{"type": "lookup", "on_missing": "boom"}],
            },
            "rules[0].expr.steps[0].on_missing",
        ),
        (
            {"type": "transform", "input": {"type": "constant", "value": 1}, "steps": "trim"},
            "rules[0].expr.steps: expected a list",
        ),
    ],
)
def test_invalid_expression_names_the_path(expr: Any, fragment: str) -> None:
    with pytest.raises(MappingInvalid) as excinfo:
        mapping_from_dict(doc_with_expr(expr))
    assert fragment in str(excinfo.value)


@pytest.mark.parametrize(
    ("mutate", "fragment"),
    [
        (lambda d: d.update(schema_version=99), "schema_version"),
        (lambda d: d.pop("name"), "missing 'name'"),
        (lambda d: d.update(rules={}), "rules: expected a list"),
        (lambda d: d["rules"].append(5), "rules[1]: expected an object"),
        (lambda d: d["rules"][0].pop("target"), "rules[0]: missing 'target'"),
        (lambda d: d["rules"][0].update(required="yes"), "rules[0].required"),
    ],
)
def test_invalid_document(mutate: Any, fragment: str) -> None:
    doc = doc_with_expr({"type": "constant", "value": 1})
    mutate(doc)
    with pytest.raises(MappingInvalid) as excinfo:
        mapping_from_dict(doc)
    assert fragment in str(excinfo.value)


def test_from_json_rejects_bad_json_and_non_objects() -> None:
    for text in ("{not json", "[]", ""):
        with pytest.raises(MappingInvalid):
            mapping_from_json(text)


def test_to_json_rejects_non_json_constants() -> None:
    from decimal import Decimal

    with pytest.raises(MappingInvalid):
        mapping_to_json(definition(rule("a", Constant(Decimal("1.5")))))
