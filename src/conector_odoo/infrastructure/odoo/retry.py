"""Retry policy shared by the network transports.

Only network-level failures of *idempotent* Odoo methods are retried. A network failure on
``create`` (or any method not in the allowlist) leaves the outcome unknown, so retrying could
duplicate records: those calls are attempted exactly once.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

IDEMPOTENT_METHODS = frozenset(
    {
        "search",
        "search_read",
        "read",
        "search_count",
        "fields_get",
        "name_search",
        "authenticate",
        "version",
    }
)
MAX_BACKOFF_SECONDS = 10.0


def is_idempotent(method: str) -> bool:
    """Return True when repeating ``method`` is safe. Unknown methods are not."""
    return method in IDEMPOTENT_METHODS


async def run_with_retry(
    call: Callable[[], Awaitable[T]],
    *,
    idempotent: bool,
    max_retries: int,
    retry_on: tuple[type[BaseException], ...],
    sleep: Callable[[float], Awaitable[None]],
    base_delay: float,
    description: str,
) -> T:
    """Run ``call``; on ``retry_on`` errors retry with exponential backoff if idempotent."""
    attempts_allowed = (max_retries if idempotent else 0) + 1
    attempt = 0
    while True:
        try:
            return await call()
        except retry_on as exc:
            attempt += 1
            if attempt >= attempts_allowed:
                raise
            delay = min(base_delay * 2 ** (attempt - 1), MAX_BACKOFF_SECONDS)
            logger.warning(
                "odoo call failed, retrying",
                extra={
                    "operation": description,
                    "attempt": attempt,
                    "delay": delay,
                    "error": type(exc).__name__,
                },
            )
            await sleep(delay)
