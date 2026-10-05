"""Executes a ``MappingDefinition`` against one ``Record``.

Pure domain: stdlib only. Data problems never raise: a failing rule yields a ``RuleError`` and
leaves its field out while the other rules continue. Money uses ``Decimal`` (never float
arithmetic); floats only appear when a number is handed to a JSON consumer.
"""

import math
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
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
    LookupMissing,
    Lower,
    MappingDefinition,
    MappingResult,
    Replace,
    RuleError,
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
from conector_odoo.domain.records import Record

_TRUE = {"true", "yes", "y", "si", "sí", "1", "on"}
_TIME_DIRECTIVES = ("%H", "%I", "%M", "%S", "%f", "%p", "%z", "%Z", "%c", "%X")
_FALSE = {"false", "no", "n", "0", "off"}


class StepFailure(Exception):
    """A value cannot go through a step; ``step_index`` is filled in by the enclosing transform."""

    def __init__(self, message: str, step_index: int | None = None) -> None:
        super().__init__(message)
        self.step_index = step_index


def apply_mapping(definition: MappingDefinition, record: Record) -> MappingResult:
    fields: dict[str, Any] = {}
    errors: list[RuleError] = []
    for rule in definition.rules:
        try:
            value = evaluate(rule.expr, record)
        except StepFailure as exc:
            errors.append(RuleError(rule.target, exc.step_index, str(exc)))
            continue
        if value is None or (rule.required and isinstance(value, str) and not value.strip()):
            if rule.required:
                errors.append(RuleError(rule.target, None, "required value is missing or empty"))
            continue
        try:
            _assign(fields, rule.target, value)
        except StepFailure as exc:
            errors.append(RuleError(rule.target, None, str(exc)))
    return MappingResult(fields, errors)


def _assign(fields: dict[str, Any], target: str, value: Any) -> None:
    *parents, leaf = target.split(".")
    node = fields
    for part in parents:
        child = node.setdefault(part, {})
        if not isinstance(child, dict):
            raise StepFailure(f"target {target!r} conflicts with a value already set for {part!r}")
        node = child
    if isinstance(node.get(leaf), dict):
        raise StepFailure(f"target {target!r} conflicts with nested targets")
    node[leaf] = value


def evaluate(expr: Expr, record: Record) -> Any:
    """Value of ``expr`` for ``record``; ``None`` means "no value"."""
    match expr:
        case Direct(source=source, default=default):
            value = record.get(source)
            return default if value is None else value
        case Constant(value=value):
            return value
        case Concat(parts=parts, separator=separator, skip_empty=skip_empty):
            texts = [_text(evaluate(part, record)) for part in parts]
            if skip_empty:
                texts = [t for t in texts if t]
            joined = separator.join(texts)
            return joined or None
        case Transform(input=inner, steps=chain):
            value = evaluate(inner, record)
            for index, step in enumerate(chain):
                try:
                    value = _apply_step(step, value, record)
                except StepFailure as exc:
                    if exc.step_index is None:
                        exc.step_index = index
                    raise
            return value
    raise StepFailure(f"unsupported expression {type(expr).__name__}")


def _is_empty(value: Any) -> bool:
    return value is None or value == ""


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float | Decimal):
        return _plain(Decimal(str(value)))
    return str(value)


def _plain(number: Decimal) -> str:
    return format(number, "f")


def _apply_step(step: Step, value: Any, record: Record) -> Any:
    match step:
        case Default(value=fallback):
            return fallback if _is_empty(value) else value
        case Coalesce(alternatives=alternatives):
            if not _is_empty(value):
                return value
            for alternative in alternatives:
                candidate = evaluate(alternative, record)
                if not _is_empty(candidate):
                    return candidate
            return None
        case Lookup():
            return _lookup(step, value)
        case ToString():
            return None if value is None else _text(value)
    if value is None:
        return None
    match step:
        case Trim() | Upper() | Lower() | Title() | Replace() | Substring():
            return _text_step(step, _require_text(value))
        case ToNumber() | ToInt() | ToBool() | ToCents() | FromCents() | DateFormat():
            if isinstance(value, str) and not value.strip():
                return None
            return _typed_step(step, value)
    raise StepFailure(f"unsupported step {type(step).__name__}")


def _require_text(value: Any) -> str:
    if not isinstance(value, str):
        raise StepFailure(f"expected text, got {type(value).__name__}")
    return value


def _text_step(step: Step, text: str) -> str:
    match step:
        case Trim():
            return text.strip()
        case Upper():
            return text.upper()
        case Lower():
            return text.lower()
        case Title():
            return text.title()
        case Replace(old=old, new=new):
            return text.replace(old, new)
        case Substring(start=start, end=end):
            return text[start:end]
    raise StepFailure("unsupported text step")


def _typed_step(step: Step, value: Any) -> Any:
    match step:
        case ToNumber():
            return _number_out(_decimal(value))
        case ToInt():
            return _integer(_decimal(value))
        case ToBool():
            return _boolean(value)
        case ToCents(factor=factor):
            try:
                return int((_decimal(value) * factor).quantize(Decimal(1), ROUND_HALF_UP))
            except InvalidOperation:
                raise StepFailure(f"amount {value!r} is out of range") from None
        case FromCents(factor=factor, as_string=as_string):
            return _from_cents(_integer(_decimal(value)), factor, as_string)
        case DateFormat(in_format=in_format, out_format=out_format):
            return _format_date(value, in_format, out_format)
    raise StepFailure("unsupported typed step")


def _decimal(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, int | float | Decimal | str):
        raise StepFailure(f"expected a number, got {value!r}")
    try:
        number = Decimal(value.strip() if isinstance(value, str) else str(value))
    except InvalidOperation:
        raise StepFailure(f"expected a number, got {value!r}") from None
    if not number.is_finite():
        raise StepFailure(f"expected a finite number, got {value!r}")
    return number


def _number_out(number: Decimal) -> int | float:
    return int(number) if number == number.to_integral_value() else float(number)


def _integer(number: Decimal) -> int:
    if number != number.to_integral_value():
        raise StepFailure(f"expected a whole number, got {_plain(number)}")
    return int(number)


def _boolean(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    token = str(value).strip().lower() if isinstance(value, int | str) else None
    if token in _TRUE:
        return True
    if token in _FALSE:
        return False
    raise StepFailure(f"cannot read {value!r} as a boolean")


def _from_cents(cents: int, factor: int, as_string: bool) -> str | float:
    places = max(len(str(factor)) - 1, 0)
    amount = (Decimal(cents) / Decimal(factor)).quantize(Decimal(1).scaleb(-places))
    return _plain(amount) if as_string else float(amount)


def _lookup(step: Lookup, value: Any) -> Any:
    if value is None:
        return None
    key = value if isinstance(value, str) else _text(value)
    if key in step.table:
        return step.table[key]
    if step.on_missing is LookupMissing.PASSTHROUGH:
        return value
    if step.on_missing is LookupMissing.DEFAULT:
        return step.default
    raise StepFailure(f"value {key!r} is not in the lookup table")


def _format_date(value: Any, in_format: str, out_format: str) -> Any:
    moment, date_only = _parse_date(value, in_format)
    if out_format == "epoch":
        return int((moment if moment.tzinfo else moment.replace(tzinfo=UTC)).timestamp())
    if out_format == "iso":
        return moment.date().isoformat() if date_only else moment.isoformat()
    return moment.strftime(out_format)


def _parse_date(value: Any, in_format: str) -> tuple[datetime, bool]:
    if isinstance(value, datetime):
        return value, False
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day), True
    try:
        if in_format == "epoch":
            if isinstance(value, bool) or not isinstance(value, int | float | str):
                raise ValueError
            seconds = float(value)
            if not math.isfinite(seconds):
                raise ValueError
            return datetime.fromtimestamp(seconds, UTC), False
        if not isinstance(value, str):
            raise ValueError
        text = value.strip()
        if in_format == "iso":
            if len(text) == 10:
                return datetime.combine(date.fromisoformat(text), datetime.min.time()), True
            return datetime.fromisoformat(text), False
        parsed = datetime.strptime(text, in_format)
        return parsed, not any(d in in_format for d in _TIME_DIRECTIVES)
    except (ValueError, OverflowError, OSError):
        raise StepFailure(f"invalid date {value!r} for format {in_format!r}") from None
