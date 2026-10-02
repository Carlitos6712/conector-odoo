"""Default event handlers and how to extend them.

Handlers are ``async def handler(event: OdooEvent) -> None`` coroutines subscribed to an event
type on the in-process bus (``InMemoryEventBus``); one handler failing never affects the others
or the HTTP response. To add your own, subscribe on the container's bus after startup, or extend
``register_default_handlers``::

    bus = app.state.container.event_bus
    bus.subscribe("partner.created", my_handler)

Event types: ``partner.created``, ``partner.updated``, ``sale_order.confirmed``
(see ``conector_odoo.domain.events``). The defaults only log; they record payload *keys*, never
values, because payloads may carry personal data.
"""

import logging

from conector_odoo.domain.events import (
    PARTNER_CREATED,
    PARTNER_UPDATED,
    SALE_ORDER_CONFIRMED,
    OdooEvent,
)
from conector_odoo.domain.ports import EventBus

logger = logging.getLogger(__name__)


def _fields(event: OdooEvent) -> dict[str, object]:
    return {
        "event_type": event.event_type,
        "model": event.model,
        "record_id": event.record_id,
        "payload_keys": sorted(event.payload),
    }


async def log_partner_event(event: OdooEvent) -> None:
    logger.info("partner event", extra=_fields(event))


async def log_sale_order_confirmed(event: OdooEvent) -> None:
    logger.info("sale order confirmed", extra=_fields(event))


def register_default_handlers(bus: EventBus) -> None:
    bus.subscribe(PARTNER_CREATED, log_partner_event)
    bus.subscribe(PARTNER_UPDATED, log_partner_event)
    bus.subscribe(SALE_ORDER_CONFIRMED, log_sale_order_confirmed)
