import logging

import pytest

from conector_odoo.application.event_bus import InMemoryEventBus
from conector_odoo.domain.events import (
    PARTNER_CREATED,
    PARTNER_UPDATED,
    SALE_ORDER_CONFIRMED,
    OdooEvent,
)
from conector_odoo.infrastructure.webhooks.handlers import register_default_handlers


@pytest.mark.parametrize(
    ("event_type", "model", "message"),
    [
        (PARTNER_CREATED, "res.partner", "partner event"),
        (PARTNER_UPDATED, "res.partner", "partner event"),
        (SALE_ORDER_CONFIRMED, "sale.order", "sale order confirmed"),
    ],
)
async def test_default_handlers_log_structured_events_without_payload_values(
    caplog: pytest.LogCaptureFixture, event_type: str, model: str, message: str
) -> None:
    bus = InMemoryEventBus()
    register_default_handlers(bus)
    event = OdooEvent(event_type, model, 7, {"name": "Ada", "token": "s3cr3t-value"})
    with caplog.at_level(logging.INFO):
        await bus.publish(event)
    record = next(r for r in caplog.records if r.getMessage() == message)
    assert record.event_type == event_type  # type: ignore[attr-defined]
    assert record.record_id == 7  # type: ignore[attr-defined]
    assert record.payload_keys == ["name", "token"]  # type: ignore[attr-defined]
    assert "s3cr3t-value" not in caplog.text
    assert "Ada" not in caplog.text
