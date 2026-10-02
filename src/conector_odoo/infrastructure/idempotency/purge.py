"""Background retention: expired records are purged from every store sharing the database."""

import asyncio
import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class _Purgeable(Protocol):
    async def purge_older_than(self, hours: float) -> int: ...


class MultiPurger:
    """Fan one ``purge_older_than`` call out to several stores; one failing never skips the rest."""

    def __init__(self, *stores: _Purgeable) -> None:
        self._stores = stores

    async def purge_older_than(self, hours: float) -> int:
        removed = 0
        for store in self._stores:
            try:
                removed += await store.purge_older_than(hours)
            except Exception:
                logger.exception("purge failed", extra={"store": type(store).__name__})
        return removed


async def purge_loop(store: _Purgeable, *, ttl_hours: float, interval_seconds: float) -> None:
    """Purge expired records now and then every ``interval_seconds`` until cancelled.

    A failing purge is logged and retried on the next tick; only cancellation ends the loop.
    """
    while True:
        try:
            removed = await store.purge_older_than(ttl_hours)
            if removed:
                logger.info(
                    "purged expired records",
                    extra={"removed": removed, "store": type(store).__name__},
                )
        except Exception:
            logger.exception("purge failed", extra={"store": type(store).__name__})
        await asyncio.sleep(interval_seconds)
