"""Dotted-path access into decoded JSON (``meta.pages``, ``data.items``; list items by index)."""

from typing import Any

MISSING: Any = object()


def dig(data: Any, path: str | None) -> Any:
    """Value at ``path`` or ``MISSING``; an empty/``None`` path is the document itself."""
    if not path:
        return data
    current = data
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part, MISSING)
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return MISSING
        else:
            return MISSING
        if current is MISSING:
            return MISSING
    return current
