"""Background retention for idempotency records."""

import asyncio
import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class _Purgeable(Protocol):
    async def purge_older_than(self, hours: float) -> int: ...


async def purge_loop(store: _Purgeable, *, ttl_hours: float, interval_seconds: float) -> None:
    """Purge expired records now and then every ``interval_seconds`` until cancelled.

    A failing purge is logged and retried on the next tick; only cancellation ends the loop.
    """
    while True:
        try:
            removed = await store.purge_older_than(ttl_hours)
            if removed:
                logger.info("purged idempotency records", extra={"removed": removed})
        except Exception:
            logger.exception("idempotency purge failed")
        await asyncio.sleep(interval_seconds)
