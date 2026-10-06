"""Sync job definition (pure domain, stdlib only).

A job connects endpoint A (``source``: profile + resource) with endpoint B (``target``). The
forward ``mapping`` turns an A record into B fields; the optional ``reverse_mapping`` turns a B
record into A fields and is mandatory for ``B_TO_A`` and ``BIDIRECTIONAL`` jobs. Triggers are only
stored and validated here; the scheduler and the webhook intake execute them (B9).
"""

import re
from dataclasses import dataclass, field
from enum import StrEnum

from conector_odoo.domain.errors import SyncJobInvalid
from conector_odoo.domain.records import RecordFilter

MAX_BATCH_SIZE = 1000
_XREF_KEY = "xref"
_FIELD_KEY_PREFIX = "field:"


class Direction(StrEnum):
    A_TO_B = "a_to_b"
    B_TO_A = "b_to_a"
    BIDIRECTIONAL = "bidirectional"


class ConflictRule(StrEnum):
    SOURCE_WINS = "source_wins"  # side A overwrites side B
    TARGET_WINS = "target_wins"  # side B overwrites side A
    NEWEST_WINS = "newest_wins"  # the side with the later ``updated_at`` field wins
    FLAG_CONFLICT = "flag_conflict"  # write nothing and record a conflict error


class TriggerKind(StrEnum):
    MANUAL = "manual"
    SCHEDULE = "schedule"
    WEBHOOK = "webhook"


@dataclass(frozen=True, slots=True)
class EndpointRef:
    profile_id: int
    resource: str

    def __post_init__(self) -> None:
        if not self.resource.strip():
            raise SyncJobInvalid("endpoint resource must not be empty")


@dataclass(frozen=True, slots=True)
class MappingRef:
    """A saved mapping by name; ``version=None`` follows the latest version."""

    name: str
    version: int | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise SyncJobInvalid("mapping name must not be empty")
        if self.version is not None and self.version < 1:
            raise SyncJobInvalid("mapping version must be >= 1")


@dataclass(frozen=True, slots=True)
class ManualTrigger:
    kind: TriggerKind = TriggerKind.MANUAL


@dataclass(frozen=True, slots=True)
class ScheduleTrigger:
    cron: str
    kind: TriggerKind = TriggerKind.SCHEDULE

    def __post_init__(self) -> None:
        validate_cron(self.cron)


@dataclass(frozen=True, slots=True)
class WebhookTrigger:
    event_types: tuple[str, ...]
    kind: TriggerKind = TriggerKind.WEBHOOK

    def __post_init__(self) -> None:
        if not self.event_types or any(not e.strip() for e in self.event_types):
            raise SyncJobInvalid("webhook trigger needs at least one non-empty event type")


Trigger = ManualTrigger | ScheduleTrigger | WebhookTrigger

_CRON_RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))  # minute hour dom month dow
_CRON_ITEM = re.compile(r"^(\*|\d+(-\d+)?)(/(\d+))?$")


def validate_cron(expression: str) -> None:
    """Classic 5-field numeric cron: ``*``, ``a``, ``a-b``, ``*/n``, ``a-b/n``, lists."""
    parts = expression.split()
    if len(parts) != 5:
        raise SyncJobInvalid("cron expression needs 5 fields (minute hour day month weekday)")
    for part, (low, high) in zip(parts, _CRON_RANGES, strict=True):
        for item in part.split(","):
            match = _CRON_ITEM.match(item)
            if match is None:
                raise SyncJobInvalid(f"invalid cron field {part!r}")
            if match.group(4) is not None and int(match.group(4)) < 1:
                raise SyncJobInvalid(f"invalid cron step in {part!r}")
            if match.group(1) != "*":
                bounds = [int(n) for n in match.group(1).split("-")]
                if any(not low <= n <= high for n in bounds) or bounds != sorted(bounds):
                    raise SyncJobInvalid(f"cron field {part!r} is out of range {low}-{high}")


@dataclass(frozen=True, slots=True)
class SyncJob:
    """``upsert_key`` is ``xref`` (rely on the cross-reference table only) or ``field:<name>``
    (before creating, look for an existing target record whose ``<name>`` equals the mapped
    value, and adopt it)."""

    id: int | None
    name: str
    source: EndpointRef
    target: EndpointRef
    mapping: MappingRef
    reverse_mapping: MappingRef | None = None
    direction: Direction = Direction.A_TO_B
    trigger: Trigger = ManualTrigger()
    record_filter: RecordFilter = field(default_factory=RecordFilter)
    batch_size: int = 100
    upsert_key: str = _XREF_KEY
    conflict_rule: ConflictRule = ConflictRule.SOURCE_WINS
    source_updated_field: str | None = None  # newest_wins: where side A keeps its change time
    target_updated_field: str | None = None  # newest_wins: where side B keeps its change time
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise SyncJobInvalid("job name must not be empty")
        if not 1 <= self.batch_size <= MAX_BATCH_SIZE:
            raise SyncJobInvalid(f"batch_size must be between 1 and {MAX_BATCH_SIZE}")
        if self.upsert_key != _XREF_KEY and not (
            self.upsert_key.startswith(_FIELD_KEY_PREFIX)
            and self.upsert_key[len(_FIELD_KEY_PREFIX) :].strip()
        ):
            raise SyncJobInvalid("upsert_key must be 'xref' or 'field:<target field>'")
        if self.direction is not Direction.A_TO_B and self.reverse_mapping is None:
            raise SyncJobInvalid(f"direction {self.direction.value} needs a reverse mapping")
        if self.conflict_rule is ConflictRule.NEWEST_WINS and not (
            self.source_updated_field and self.target_updated_field
        ):
            raise SyncJobInvalid("newest_wins needs an updated-at field path for both sides")

    @property
    def key_field(self) -> str | None:
        """The ``<name>`` of a ``field:<name>`` upsert key, ``None`` for ``xref``."""
        if self.upsert_key.startswith(_FIELD_KEY_PREFIX):
            return self.upsert_key[len(_FIELD_KEY_PREFIX) :]
        return None
