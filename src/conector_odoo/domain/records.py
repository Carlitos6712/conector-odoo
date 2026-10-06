"""Generic record model shared by every source and sink (Odoo, REST, ...).

Pure domain: stdlib only. Sync and mapping logic talks to ``Record`` / ``ResourceSchema`` and never
to Odoo- or REST-specific shapes.
"""

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any

_MISSING: Any = object()


class FieldType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    OBJECT = "object"
    ARRAY = "array"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class FieldSpec:
    name: str
    type: FieldType
    required: bool = False
    readonly: bool = False
    label: str | None = None
    choices: tuple[str, ...] | None = None
    relation: str | None = None  # name of the related resource, when the field is a reference


@dataclass(frozen=True, slots=True)
class ResourceSchema:
    name: str
    label: str
    fields: tuple[FieldSpec, ...]
    id_field: str = "id"

    def field(self, name: str) -> FieldSpec | None:
        return next((spec for spec in self.fields if spec.name == name), None)


@dataclass(frozen=True, slots=True)
class Record:
    """One remote record. ``id`` is ``None`` until the remote system assigns one.

    ``fields`` is deep-copied on construction and exposed read-only; ``get`` hands out copies of
    nested containers, so a record cannot be changed after creation.
    """

    id: str | None
    fields: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "fields", MappingProxyType(deepcopy(dict(self.fields))))

    def get(self, path: str, default: Any = None) -> Any:
        """Read a value by dotted path (``address.city``; list items by index: ``lines.0.sku``).

        Returns ``default`` when any step is missing; an existing ``None`` value is returned as is.
        """
        current: Any = self.fields
        for part in path.split("."):
            current = _step(current, part)
            if current is _MISSING:
                return default
        return deepcopy(current)


def _step(container: Any, key: str) -> Any:
    if isinstance(container, Mapping):
        return container.get(key, _MISSING)
    if isinstance(container, Sequence) and not isinstance(container, str | bytes):
        try:
            return container[int(key)]
        except (ValueError, IndexError):
            return _MISSING
    return _MISSING


@dataclass(frozen=True, slots=True)
class RecordPage:
    records: tuple[Record, ...]
    next_cursor: str | None = None
    total: int | None = None


@dataclass(frozen=True, slots=True)
class RecordFilter:
    """Adapter-agnostic selection: exact matches, a lower bound on modification time and an
    adapter-specific ``raw`` passthrough (e.g. an Odoo domain or extra query parameters)."""

    equals: Mapping[str, Any] = field(default_factory=dict)
    since: datetime | None = None
    raw: Mapping[str, Any] | None = None
