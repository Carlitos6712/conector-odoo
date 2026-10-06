from decimal import Decimal
from typing import Any

import pytest

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
    Transform,
    Trim,
    Upper,
)
from conector_odoo.domain.mapping_engine import apply_mapping
from tests.mapping.helpers import definition, rec, rule, steps


def run(expr: Any, **fields: Any) -> Any:
    result = apply_mapping(definition(rule("out", expr)), rec(**fields))
    assert not result.errors, result.errors
    return result.fields.get("out", "<omitted>")


def error_of(expr: Any, **fields: Any) -> Any:
    result = apply_mapping(definition(rule("out", expr)), rec(**fields))
    assert len(result.errors) == 1
    assert "out" not in result.fields
    return result.errors[0]


# -- direct / constant -------------------------------------------------------------------------


def test_direct_reads_dotted_path_and_list_index() -> None:
    assert run(Direct("a.b"), a={"b": 5}) == 5
    assert run(Direct("lines.0.sku"), lines=[{"sku": "X"}]) == "X"


def test_direct_missing_or_none_is_omitted() -> None:
    assert run(Direct("nope")) == "<omitted>"
    assert run(Direct("a"), a=None) == "<omitted>"


def test_direct_default_applies_to_missing_and_none_but_not_empty_string() -> None:
    assert run(Direct("nope", default="x")) == "x"
    assert run(Direct("a", default="x"), a=None) == "x"
    assert run(Direct("a", default="x"), a="") == ""
    assert run(Direct("a", default=0), a=None) == 0


def test_constant_including_falsy_values() -> None:
    assert run(Constant("fixed")) == "fixed"
    assert run(Constant(False)) is False
    assert run(Constant(0)) == 0
    assert run(Constant(None)) == "<omitted>"


# -- concat ------------------------------------------------------------------------------------


def test_concat_joins_with_separator_and_skips_empty_parts() -> None:
    expr = Concat((Direct("a"), Direct("b"), Constant("z")), separator=" ")
    assert run(expr, a="Ana", b="") == "Ana z"
    assert run(expr, a="Ana", b="Perez") == "Ana Perez z"


def test_concat_keeps_empty_parts_when_skip_empty_is_false() -> None:
    expr = Concat((Direct("a"), Direct("b")), separator="-", skip_empty=False)
    assert run(expr, a="x") == "x-"


def test_concat_of_only_empty_parts_is_omitted() -> None:
    assert run(Concat((Direct("a"), Direct("b")), separator=" ")) == "<omitted>"


def test_concat_formats_numbers_and_booleans_as_text() -> None:
    expr = Concat((Direct("n"), Direct("f"), Direct("b")), separator="|")
    assert run(expr, n=3, f=2.5, b=True) == "3|2.5|true"


# -- text steps --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("step", "value", "expected"),
    [
        (Trim(), "  hi \n", "hi"),
        (Upper(), "abC", "ABC"),
        (Lower(), "AbC", "abc"),
        (Title(), "juan PEREZ", "Juan Perez"),
        (Replace("-", ""), "a-b-c", "abc"),
        (Substring(1, 3), "abcdef", "bc"),
        (Substring(2, None), "abcdef", "cdef"),
        (Substring(0, 99), "abc", "abc"),
        (Trim(), "", ""),
    ],
)
def test_text_steps(step: Any, value: str, expected: str) -> None:
    assert run(steps(Direct("v"), step), v=value) == expected


@pytest.mark.parametrize("step", [Trim(), Upper(), Lower(), Title(), Substring(0, 1)])
def test_text_steps_pass_none_through_and_reject_non_text(step: Any) -> None:
    assert run(steps(Direct("v"), step)) == "<omitted>"
    err = error_of(steps(Direct("v"), step), v=12)
    assert err.step_index == 0
    assert "text" in err.message


def test_replace_rejects_non_text() -> None:
    assert error_of(steps(Direct("v"), Replace("a", "b")), v=1).step_index == 0


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (5, "5"),
        (2.5, "2.5"),
        (True, "true"),
        (Decimal("1.50"), "1.50"),
        ("x", "x"),
        (1e20, "100000000000000000000"),
    ],
)
def test_to_string(value: Any, expected: str) -> None:
    assert run(steps(Direct("v"), ToString()), v=value) == expected


# -- numbers -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [("12", 12), (" 3.5 ", 3.5), (7, 7), (2.0, 2), ("-0.25", -0.25), ("1e2", 100)],
)
def test_to_number(value: Any, expected: Any) -> None:
    got = run(steps(Direct("v"), ToNumber()), v=value)
    assert got == expected


@pytest.mark.parametrize("value", ["abc", True, "NaN", "Infinity", [1]])
def test_to_number_invalid(value: Any) -> None:
    assert error_of(steps(Direct("v"), ToNumber()), v=value).step_index == 0


def test_to_number_empty_string_is_omitted() -> None:
    assert run(steps(Direct("v"), ToNumber()), v="  ") == "<omitted>"


@pytest.mark.parametrize(("value", "expected"), [("12", 12), ("3.0", 3), (4, 4), (4.0, 4)])
def test_to_int(value: Any, expected: int) -> None:
    got = run(steps(Direct("v"), ToInt()), v=value)
    assert got == expected
    assert isinstance(got, int)


@pytest.mark.parametrize("value", ["3.5", "x", 2.5, False])
def test_to_int_rejects_fractions_and_garbage(value: Any) -> None:
    assert error_of(steps(Direct("v"), ToInt()), v=value).step_index == 0


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, True),
        (False, False),
        (1, True),
        (0, False),
        ("true", True),
        ("Yes", True),
        ("SI", True),
        ("1", True),
        ("false", False),
        ("no", False),
        ("0", False),
        ("off", False),
    ],
)
def test_to_bool(value: Any, expected: bool) -> None:
    assert run(steps(Direct("v"), ToBool()), v=value) is expected


@pytest.mark.parametrize("value", ["maybe", 2, 1.5])
def test_to_bool_invalid(value: Any) -> None:
    assert error_of(steps(Direct("v"), ToBool()), v=value).step_index == 0


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("12.34", 1234),
        (12.34, 1234),
        (Decimal("0.005"), 1),  # half up
        ("0.004", 0),
        ("1.005", 101),  # exact decimal arithmetic: float 1.005 would give 100
        ("-0.005", -1),  # half away from zero
        ("-12.345", -1235),
        (7, 700),
        ("0", 0),
    ],
)
def test_to_cents_uses_decimal_half_up(value: Any, expected: int) -> None:
    got = run(steps(Direct("v"), ToCents()), v=value)
    assert got == expected
    assert isinstance(got, int)


def test_to_cents_custom_factor() -> None:
    assert run(steps(Direct("v"), ToCents(factor=1000)), v="1.2345") == 1235


@pytest.mark.parametrize("value", ["abc", True, "NaN"])
def test_to_cents_invalid(value: Any) -> None:
    assert error_of(steps(Direct("v"), ToCents()), v=value).step_index == 0


@pytest.mark.parametrize(
    ("value", "expected"),
    [(1234, "12.34"), (5, "0.05"), (0, "0.00"), (-1234, "-12.34"), ("100", "1.00"), (-5, "-0.05")],
)
def test_from_cents_string(value: Any, expected: str) -> None:
    assert run(steps(Direct("v"), FromCents()), v=value) == expected


def test_from_cents_as_number_and_factor() -> None:
    assert run(steps(Direct("v"), FromCents(as_string=False)), v=1234) == 12.34
    assert run(steps(Direct("v"), FromCents(factor=1000)), v=1234) == "1.234"


@pytest.mark.parametrize("value", [12.5, "x", True])
def test_from_cents_requires_integer(value: Any) -> None:
    assert error_of(steps(Direct("v"), FromCents()), v=value).step_index == 0


# -- dates -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("step", "value", "expected"),
    [
        (DateFormat("iso", "%d/%m/%Y"), "2024-03-05", "05/03/2024"),
        (DateFormat("iso", "%Y%m%d"), "2024-03-05T10:20:30", "20240305"),
        (DateFormat("%d/%m/%Y", "iso"), "05/03/2024", "2024-03-05"),
        (DateFormat("%d/%m/%Y %H:%M", "iso"), "05/03/2024 10:20", "2024-03-05T10:20:00"),
        (DateFormat("iso", "iso"), "2024-03-05T10:20:30Z", "2024-03-05T10:20:30+00:00"),
        (DateFormat("epoch", "iso"), 86400, "1970-01-02T00:00:00+00:00"),
        (DateFormat("epoch", "iso"), "86400", "1970-01-02T00:00:00+00:00"),
        (DateFormat("iso", "epoch"), "1970-01-02T00:00:00+00:00", 86400),
        (DateFormat("iso", "epoch"), "1970-01-02", 86400),
    ],
)
def test_date_format(step: Any, value: Any, expected: Any) -> None:
    assert run(steps(Direct("v"), step), v=value) == expected


@pytest.mark.parametrize(
    ("step", "value"),
    [
        (DateFormat("iso", "iso"), "not a date"),
        (DateFormat("iso", "iso"), "2024-13-45"),
        (DateFormat("%d/%m/%Y", "iso"), "2024-03-05"),
        (DateFormat("epoch", "iso"), "abc"),
        (DateFormat("iso", "iso"), 12),
    ],
)
def test_date_format_invalid(step: Any, value: Any) -> None:
    err = error_of(steps(Direct("v"), step), v=value)
    assert err.step_index == 0
    assert "date" in err.message


def test_date_format_empty_string_is_omitted() -> None:
    assert run(steps(Direct("v"), DateFormat("iso", "iso")), v="") == "<omitted>"


# -- lookup / default / coalesce ---------------------------------------------------------------


TABLE = {"M": "male", "F": "female", "1": "one", "true": "yes"}


def test_lookup_hit_including_non_text_keys() -> None:
    assert run(steps(Direct("v"), Lookup(TABLE)), v="M") == "male"
    assert run(steps(Direct("v"), Lookup(TABLE)), v=1) == "one"
    assert run(steps(Direct("v"), Lookup(TABLE)), v=True) == "yes"


def test_lookup_missing_error_policy_is_default() -> None:
    err = error_of(steps(Direct("v"), Lookup(TABLE)), v="X")
    assert err.step_index == 0
    assert "'X'" in err.message


def test_lookup_missing_passthrough_and_default() -> None:
    assert run(steps(Direct("v"), Lookup(TABLE, LookupMissing.PASSTHROUGH)), v="X") == "X"
    assert run(steps(Direct("v"), Lookup(TABLE, LookupMissing.DEFAULT, "other")), v="X") == "other"


def test_lookup_none_passes_through() -> None:
    assert run(steps(Direct("v"), Lookup(TABLE))) == "<omitted>"


def test_default_fills_none_and_empty_only() -> None:
    assert run(steps(Direct("v"), Default("n/a"))) == "n/a"
    assert run(steps(Direct("v"), Default("n/a")), v="") == "n/a"
    assert run(steps(Direct("v"), Default("n/a")), v="x") == "x"
    assert run(steps(Direct("v"), Default("n/a")), v=0) == 0


def test_coalesce_takes_first_non_empty_alternative() -> None:
    expr = steps(Direct("a"), Coalesce((Direct("b"), Direct("c"), Constant("z"))))
    assert run(expr, a="A") == "A"
    assert run(expr, a="", b=None, c="C") == "C"
    assert run(expr) == "z"


def test_coalesce_without_any_value_is_omitted() -> None:
    assert run(steps(Direct("a"), Coalesce((Direct("b"),)))) == "<omitted>"


def test_coalesce_alternative_error_is_reported() -> None:
    expr = steps(Direct("a"), Coalesce((steps(Direct("b"), ToInt()),)))
    assert error_of(expr, b="x").step_index == 0


# -- chains / nesting --------------------------------------------------------------------------


def test_chain_order_and_step_index_of_failure() -> None:
    expr = steps(Direct("v"), Trim(), Upper(), ToInt())
    assert run(expr, v=" 12 ") == 12  # trim -> upper -> to_int on "12"
    assert error_of(expr, v=" ab ").step_index == 2


def test_nested_transform_as_input_and_concat_part() -> None:
    inner = steps(Direct("a"), Trim(), Upper())
    assert run(steps(inner, Replace("X", "-"))) == "<omitted>"
    assert run(steps(inner, Replace("X", "-")), a=" xy ") == "-Y"
    expr = Concat((inner, Direct("b")), separator="/")  # type: ignore[arg-type]
    assert run(expr, a=" q ", b="r") == "Q/r"


# -- rules -------------------------------------------------------------------------------------


def test_dotted_targets_build_nested_dicts() -> None:
    d = definition(rule("address.city", Direct("c")), rule("address.zip", Direct("z")))
    result = apply_mapping(d, rec(c="Madrid", z="28001"))
    assert result.fields == {"address": {"city": "Madrid", "zip": "28001"}}
    assert not result.errors


def test_required_rule_reports_missing_none_and_blank() -> None:
    d = definition(rule("name", Direct("n"), required=True))
    for fields in ({}, {"n": None}, {"n": ""}, {"n": "   "}):
        result = apply_mapping(d, rec(**fields))
        assert result.fields == {}
        assert [e.rule_target for e in result.errors] == ["name"]
        assert result.errors[0].step_index is None
        assert "required" in result.errors[0].message


def test_required_rule_satisfied_by_default() -> None:
    d = definition(rule("name", Direct("n", default="anon"), required=True))
    assert apply_mapping(d, rec()).fields == {"name": "anon"}


def test_optional_empty_string_is_kept_and_zero_false_are_not_empty() -> None:
    d = definition(rule("a", Direct("a")), rule("b", Direct("b")), rule("c", Direct("c")))
    assert apply_mapping(d, rec(a="", b=0, c=False)).fields == {"a": "", "b": 0, "c": False}


def test_failing_rule_is_isolated_from_the_others() -> None:
    d = definition(
        rule("ok1", Direct("a")),
        rule("bad", steps(Direct("n"), ToInt())),
        rule("ok2", Constant("k")),
        rule("req", Direct("missing"), required=True),
    )
    result = apply_mapping(d, rec(a="A", n="x"))
    assert result.fields == {"ok1": "A", "ok2": "k"}
    assert [(e.rule_target, e.step_index) for e in result.errors] == [("bad", 0), ("req", None)]


def test_runtime_target_conflict_is_an_error_not_an_exception() -> None:
    d = definition(rule("a", Constant(1)), rule("a.b", Constant(2)))
    result = apply_mapping(d, rec())
    assert result.fields == {"a": 1}
    assert [e.rule_target for e in result.errors] == ["a.b"]


def test_record_is_not_mutated_and_output_is_independent() -> None:
    source = rec(tags=["x"])
    result = apply_mapping(definition(rule("t", Direct("tags"))), source)
    result.fields["t"].append("y")
    assert source.get("tags") == ["x"]


def test_transform_is_a_valid_top_level_expression_type() -> None:
    assert isinstance(steps(Direct("a"), Trim()), Transform)


# -- huge exponents must not be materialised -----------------------------------------------------


@pytest.mark.parametrize("step", [ToInt(), ToNumber()])
@pytest.mark.parametrize("value", ["1e999999999", "-1E+400", "1e-999999999", "9" * 400, 10**400])
def test_out_of_range_numbers_fail_the_step_quickly(step: Any, value: Any) -> None:
    import time

    started = time.perf_counter()
    error = error_of(steps(Direct("v"), step), v=value)
    assert time.perf_counter() - started < 1.0
    assert error.step_index == 0 and "range" in error.message


@pytest.mark.parametrize("step", [ToCents(), FromCents()])
def test_out_of_range_amounts_fail_cents_steps_too(step: Any) -> None:
    assert error_of(steps(Direct("v"), step), v="1e999999999").step_index == 0


def test_large_but_sane_numbers_still_convert() -> None:
    assert run(steps(Direct("v"), ToInt()), v="1e10") == 10_000_000_000
    assert run(steps(Direct("v"), ToNumber()), v="12345678901234567890") == 12345678901234567890
