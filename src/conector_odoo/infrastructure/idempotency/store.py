"""``IdempotencyStore`` port (infrastructure-only concern) and its record type."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol

Status = Literal["in_progress", "completed"]


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
    async def begin(self, key: str, scope: str, request_hash: str) -> IdempotencyRecord | None:
        """Atomically claim ``(key, scope)``.

        Returns ``None`` when this call inserted the ``in_progress`` record (the caller owns the
        key), or the already existing record otherwise.
        """
        ...

    async def get(self, key: str, scope: str) -> IdempotencyRecord | None: ...

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
