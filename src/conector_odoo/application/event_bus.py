"""In-process event bus: handlers are isolated so one failure never affects others."""

import logging
from collections import defaultdict

from conector_odoo.domain.events import OdooEvent
from conector_odoo.domain.ports import EventHandler

logger = logging.getLogger(__name__)


class InMemoryEventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        self._handlers[event_type].append(handler)

    async def publish(self, event: OdooEvent) -> None:
        for handler in list(self._handlers.get(event.event_type, [])):
            try:
                await handler(event)
            except Exception:
                logger.exception(
                    "event handler failed",
                    extra={"event_type": event.event_type, "record_id": event.record_id},
                )
