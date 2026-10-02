"""Helpers to convert Odoo field values into plain Python values."""

from typing import Any


def text_or_none(value: Any) -> str | None:
    """Odoo returns ``False`` for empty char/text fields."""
    if value is False or value is None or value == "":
        return None
    return str(value)


def many2one_id(value: Any) -> int | None:
    """A many2one comes as ``[id, display_name]`` (or ``False`` when empty)."""
    if isinstance(value, (list, tuple)) and value:
        return int(value[0])
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def many2one_name(value: Any) -> str | None:
    if isinstance(value, (list, tuple)) and len(value) > 1:
        return text_or_none(value[1])
    return None
