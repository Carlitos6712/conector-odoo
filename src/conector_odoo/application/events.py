"""Use case for events pushed by Odoo."""

import logging

from conector_odoo.domain.events import OdooEvent
from conector_odoo.domain.ports import EventBus

logger = logging.getLogger(__name__)


class HandleOdooEvent:
    def __init__(self, bus: EventBus) -> None:
        self._bus = bus

    async def execute(self, event: OdooEvent) -> bool:
        """Publish the event; ``True`` when every handler succeeded (callers may mark it done)."""
        logger.info(
            "odoo event received",
            extra={
                "event_type": event.event_type,
                "model": event.model,
                "record_id": event.record_id,
            },
        )
        return await self._bus.publish(event)
