import logging

import pytest

from conector_odoo.application.event_bus import InMemoryEventBus
from conector_odoo.application.events import HandleOdooEvent
from conector_odoo.domain.events import (
    PARTNER_CREATED,
    PARTNER_UPDATED,
    SALE_ORDER_CONFIRMED,
    OdooEvent,
)


def _event(event_type: str = PARTNER_CREATED) -> OdooEvent:
    return OdooEvent(event_type=event_type, model="res.partner", record_id=1, payload={"a": 1})


def test_event_type_constants() -> None:
    assert PARTNER_CREATED == "partner.created"
    assert PARTNER_UPDATED == "partner.updated"
    assert SALE_ORDER_CONFIRMED == "sale_order.confirmed"


def test_event_has_occurred_at_default() -> None:
    assert _event().occurred_at.tzinfo is not None


async def test_bus_calls_only_matching_handlers() -> None:
    bus = InMemoryEventBus()
    seen: list[str] = []

    async def on_created(event: OdooEvent) -> None:
        seen.append("created")

    async def on_updated(event: OdooEvent) -> None:
        seen.append("updated")

    bus.subscribe(PARTNER_CREATED, on_created)
    bus.subscribe(PARTNER_UPDATED, on_updated)
    await bus.publish(_event(PARTNER_CREATED))
    assert seen == ["created"]


async def test_bus_isolates_handler_failures(caplog: pytest.LogCaptureFixture) -> None:
    bus = InMemoryEventBus()
    seen: list[int] = []

    async def bad(event: OdooEvent) -> None:
        raise RuntimeError("boom")

    async def good(event: OdooEvent) -> None:
        seen.append(event.record_id)

    bus.subscribe(PARTNER_CREATED, bad)
    bus.subscribe(PARTNER_CREATED, good)
    with caplog.at_level(logging.ERROR):
        await bus.publish(_event())
    assert seen == [1]
    assert any("handler failed" in r.getMessage() for r in caplog.records)


async def test_publish_without_handlers_is_noop() -> None:
    await InMemoryEventBus().publish(_event())


async def test_handle_odoo_event_publishes_to_bus() -> None:
    bus = InMemoryEventBus()
    received: list[OdooEvent] = []

    async def handler(event: OdooEvent) -> None:
        received.append(event)

    bus.subscribe(SALE_ORDER_CONFIRMED, handler)
    event = _event(SALE_ORDER_CONFIRMED)
    await HandleOdooEvent(bus).execute(event)
    assert received == [event]


async def test_publish_reports_whether_every_handler_succeeded() -> None:
    bus = InMemoryEventBus()
    assert await bus.publish(_event()) is True  # no handlers: nothing failed

    async def good(event: OdooEvent) -> None:
        return None

    async def bad(event: OdooEvent) -> None:
        raise RuntimeError("boom")

    bus.subscribe(PARTNER_CREATED, good)
    assert await bus.publish(_event()) is True
    bus.subscribe(PARTNER_CREATED, bad)
    assert await bus.publish(_event()) is False


async def test_handle_odoo_event_returns_the_bus_outcome() -> None:
    bus = InMemoryEventBus()

    async def bad(event: OdooEvent) -> None:
        raise RuntimeError("boom")

    assert await HandleOdooEvent(bus).execute(_event()) is True
    bus.subscribe(PARTNER_CREATED, bad)
    assert await HandleOdooEvent(bus).execute(_event()) is False
