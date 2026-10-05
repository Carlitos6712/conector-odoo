"""Mapping model: how one source record becomes the fields of a target record.

Pure domain: stdlib only. A ``MappingDefinition`` is a list of rules; each rule computes one
target field (dotted for nested targets) from an expression tree. Expressions and transform steps
are frozen dataclasses so a definition can be compared, stored as versioned JSON (see
``mapping_codec``) and executed without side effects (see ``mapping_engine``).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from conector_odoo.domain.errors import ConnectorError

SCHEMA_VERSION = 1


class LookupMissing(StrEnum):
    ERROR = "error"
    PASSTHROUGH = "passthrough"
    DEFAULT = "default"


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


# -- expressions -------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Direct:
    """Value at a dotted source path. ``default`` replaces a missing or ``None`` value."""

    source: str
    default: Any = None


@dataclass(frozen=True, slots=True)
class Constant:
    value: Any


@dataclass(frozen=True, slots=True)
class Concat:
    """Text parts joined by ``separator``; empty parts are dropped when ``skip_empty``."""

    parts: tuple["Expr", ...]
    separator: str = ""
    skip_empty: bool = True


@dataclass(frozen=True, slots=True)
class Transform:
    input: "Expr"
    steps: tuple["Step", ...] = ()


# -- transform steps ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Trim:
    pass


@dataclass(frozen=True, slots=True)
class Upper:
    pass


@dataclass(frozen=True, slots=True)
class Lower:
    pass


@dataclass(frozen=True, slots=True)
class Title:
    pass


@dataclass(frozen=True, slots=True)
class ToString:
    pass


@dataclass(frozen=True, slots=True)
class ToNumber:
    pass


@dataclass(frozen=True, slots=True)
class ToInt:
    pass


@dataclass(frozen=True, slots=True)
class ToBool:
    pass


@dataclass(frozen=True, slots=True)
class Replace:
    old: str
    new: str


@dataclass(frozen=True, slots=True)
class Default:
    """Replaces a ``None`` or empty-string value."""

    value: Any


@dataclass(frozen=True, slots=True)
class DateFormat:
    """``in_format``: ``iso``, ``epoch`` (seconds) or a ``strptime`` pattern; ``out_format``:
    ``iso``, ``epoch`` or a ``strftime`` pattern."""

    in_format: str = "iso"
    out_format: str = "iso"


@dataclass(frozen=True, slots=True)
class ToCents:
    """Decimal amount -> integer minor units (``Decimal``, round half up)."""

    factor: int = 100


@dataclass(frozen=True, slots=True)
class FromCents:
    """Integer minor units -> decimal with ``log10(factor)`` places (text unless ``as_string``
    is false)."""

    factor: int = 100
    as_string: bool = True


@dataclass(frozen=True, slots=True)
class Lookup:
    table: Mapping[str, Any] = field(default_factory=dict)
    on_missing: LookupMissing = LookupMissing.ERROR
    default: Any = None


@dataclass(frozen=True, slots=True)
class Coalesce:
    """When the value is empty, the first non-empty alternative replaces it."""

    alternatives: tuple["Expr", ...] = ()


@dataclass(frozen=True, slots=True)
class Substring:
    start: int = 0
    end: int | None = None


Expr = Direct | Constant | Concat | Transform
Step = (
    Trim
    | Upper
    | Lower
    | Title
    | ToString
    | ToNumber
    | ToInt
    | ToBool
    | Replace
    | Default
    | DateFormat
    | ToCents
    | FromCents
    | Lookup
    | Coalesce
    | Substring
)


# -- definition --------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MappingRule:
    """``target`` may be dotted (``address.city``) to build nested output."""

    target: str
    expr: Expr
    required: bool = False


@dataclass(frozen=True, slots=True)
class MappingDefinition:
    name: str
    source_resource: str
    target_resource: str
    rules: tuple[MappingRule, ...] = ()
    schema_version: int = SCHEMA_VERSION


# -- results -----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RuleError:
    rule_target: str
    step_index: int | None
    message: str


@dataclass(frozen=True, slots=True)
class MappingResult:
    fields: dict[str, Any]
    errors: list[RuleError]


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    path: str
    severity: Severity
    message: str


@dataclass(frozen=True, slots=True)
class StoredMapping:
    """One saved version of a mapping."""

    name: str
    version: int
    definition: MappingDefinition
    created_at: datetime


class MappingValidationFailed(ConnectorError):
    """A definition has blocking validation errors; ``issues`` lists every finding."""

    def __init__(self, issues: list[ValidationIssue]) -> None:
        errors = [i for i in issues if i.severity is Severity.ERROR]
        super().__init__("; ".join(f"{i.path}: {i.message}" for i in errors) or "invalid mapping")
        self.issues = list(issues)
