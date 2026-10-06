"""``IdempotencyStore`` port (infrastructure-only concern) and its record type."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol

# An ``in_progress`` claim older than this is treated as abandoned (single source of truth; the
# ``idempotency_in_progress_timeout_seconds`` setting and the SQLite store both default to it).
DEFAULT_IN_PROGRESS_TIMEOUT_SECONDS = 300.0

# ``unknown``: the write may or may not have been applied in Odoo (uncertain failure or an
# abandoned ``in_progress`` claim). The key stays blocked until it is purged.
Status = Literal["in_progress", "completed", "unknown"]


@dataclass(frozen=True)
class IdempotencyRecord:
    key: str
    scope: str
    request_hash: str
    status: Status
    response_status: int | None = None
    response_body: str | None = None
    response_headers: dict[str, str] = field(default_factory=dict)


class IdempotencyStore(Protocol):
    async def begin(
        self, key: str, scope: str, request_hash: str, *, now: datetime | None = None
    ) -> IdempotencyRecord | None:
        """Atomically claim ``(key, scope)``.

        Returns ``None`` when this call inserted the ``in_progress`` record (the caller owns the
        key), or the already existing record otherwise. An ``in_progress`` record older than the
        store's in-progress timeout is abandoned: it is converted to ``unknown`` and returned
        (never silently re-run). ``now`` is a test seam.
        """
        ...

    async def get(self, key: str, scope: str) -> IdempotencyRecord | None:
        """Read a record without claiming or mutating it (inspection helper for tests/tools)."""
        ...

    async def mark_unknown(
        self,
        key: str,
        scope: str,
        response_status: int | None,
        response_body: str | None,
        response_headers: dict[str, str],
    ) -> None:
        """Keep the key blocked because the write may have happened; store the error response."""
        ...

    async def complete(
        self,
        key: str,
        scope: str,
        response_status: int,
        response_body: str,
        response_headers: dict[str, str],
    ) -> None: ...

    async def release(self, key: str, scope: str) -> None:
        """Delete the record so the client may retry with the same key."""
        ...

    async def purge_older_than(self, hours: float, *, now: datetime | None = None) -> int:
        """Delete records created more than ``hours`` ago; returns how many were removed."""
        ...

    async def close(self) -> None: ...
