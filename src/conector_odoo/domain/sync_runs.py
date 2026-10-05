"""Run, run-error and cross-reference models of the sync engine (pure domain, stdlib only)."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

_SECRET_MARKERS = ("password", "passwd", "secret", "token", "api_key", "apikey", "authorization")
_MAX_TEXT = 500
_MASK = "***"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"  # finished, but some records failed or conflicted
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_active(self) -> bool:
        return self in (RunStatus.QUEUED, RunStatus.RUNNING)


class ErrorKind(StrEnum):
    MAPPING = "mapping"
    REJECTED = "rejected"
    REMOTE = "remote"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    OTHER = "other"


class Side(StrEnum):
    """Which endpoint of the job a ``record_ref`` belongs to."""

    SOURCE = "source"
    TARGET = "target"


@dataclass(slots=True)
class RunCounters:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    conflicts: int = 0

    @property
    def processed(self) -> int:
        return self.created + self.updated + self.skipped + self.failed


@dataclass(frozen=True, slots=True)
class SyncRun:
    id: int
    job_id: int
    status: RunStatus
    trigger: str
    dry_run: bool
    counters: RunCounters
    started_at: datetime
    finished_at: datetime | None = None
    heartbeat_at: datetime | None = None
    checkpoint: dict[str, Any] = field(default_factory=dict)
    parent_run_id: int | None = None
    options: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    sample: list[dict[str, Any]] = field(default_factory=list)
    cancel_requested: bool = False

    @property
    def duration_seconds(self) -> float | None:
        if self.finished_at is None:
            return None
        return (self.finished_at - self.started_at).total_seconds()


@dataclass(frozen=True, slots=True)
class RunErrorData:
    """One failed record, as written by the runner."""

    record_ref: str | None
    message: str
    side: Side = Side.SOURCE
    kind: ErrorKind = ErrorKind.OTHER
    retryable: bool = True
    payload: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class RunError:
    id: int
    run_id: int
    record_ref: str | None
    message: str
    side: Side
    kind: ErrorKind
    retryable: bool
    retried: bool
    payload: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class RunFilter:
    job_id: int | None = None
    status: RunStatus | None = None
    started_from: datetime | None = None
    started_to: datetime | None = None


@dataclass(frozen=True, slots=True)
class XRef:
    """Pairs record ``source_id`` (side A) with ``target_id`` (side B) for one job and resource.

    ``content_hash`` is the hash of what the forward mapping produced from A at the last sync;
    ``reverse_hash`` the hash of what the reverse mapping produced from B at the last sync
    (``None`` for one-way jobs). A side whose current hash differs changed since the last sync.
    """

    job_id: int
    resource: str
    source_id: str
    target_id: str
    content_hash: str | None
    reverse_hash: str | None
    synced_at: datetime


def redact_payload(value: Any) -> Any:
    """Copy of ``value`` safe to persist: secret-looking keys are masked and long text is cut."""
    if isinstance(value, dict):
        return {
            key: _MASK if _is_secret(str(key)) else redact_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [redact_payload(item) for item in value]
    if isinstance(value, str) and len(value) > _MAX_TEXT:
        return value[:_MAX_TEXT] + "..."
    return value


def _is_secret(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in _SECRET_MARKERS)
