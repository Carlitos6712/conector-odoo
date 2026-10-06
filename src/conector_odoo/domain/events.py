"""Events emitted by Odoo and consumed in-process."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

PARTNER_CREATED = "partner.created"
PARTNER_UPDATED = "partner.updated"
SALE_ORDER_CONFIRMED = "sale_order.confirmed"

KNOWN_EVENT_TYPES = frozenset({PARTNER_CREATED, PARTNER_UPDATED, SALE_ORDER_CONFIRMED})


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class OdooEvent:
    event_type: str
    model: str
    record_id: int
    payload: dict[str, Any] = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=_now)
