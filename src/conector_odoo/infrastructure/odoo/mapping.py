"""Helpers to convert Odoo field values into plain Python values."""

from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from conector_odoo.domain.errors import ConnectorError, CreatedButUnreadable

T = TypeVar("T")


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


async def read_back(
    model: str, record_id: int, label: str, reader: Callable[[], Awaitable[T | None]]
) -> T:
    """Read a just-created record; failure means it exists in Odoo but is unreadable.

    Raises ``CreatedButUnreadable`` (never a plain failure) so callers do not blindly retry
    the ``create`` and duplicate the record.
    """
    message = f"{label} {record_id} was created but could not be read back"
    try:
        record = await reader()
    except ConnectorError as exc:
        raise CreatedButUnreadable(model, record_id, message) from exc
    if record is None:
        raise CreatedButUnreadable(model, record_id, message)
    return record
