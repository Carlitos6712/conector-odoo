"""Dependency-free helpers for the connector webhook: event body, signing and delivery.

This module deliberately does NOT import ``odoo`` so it can be unit-tested (and verified against
the connector's ``verify``) outside Odoo. The model in ``connector_webhook.py`` is a thin Odoo
wrapper around it.

Wire contract (must match ``conector_odoo.infrastructure.webhooks.signature`` in the connector)::

    body       = json.dumps(event, separators=(",", ":")).encode("utf-8")   # serialised ONCE
    timestamp  = unix seconds (ASCII digits)
    message    = f"{timestamp}.".encode("utf-8") + body
    signature  = HMAC-SHA256(secret.encode("utf-8"), message).hexdigest()   # lowercase hex

    Content-Type: application/json
    X-Odoo-Timestamp: <timestamp>
    X-Odoo-Signature: sha256=<signature>

The HTTP client must send exactly ``body`` (``data=body``, never ``json=...``): re-serialising
after signing would break the MAC.
"""

import hashlib
import hmac
import json
import logging
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

_logger = logging.getLogger(__name__)

SIGNATURE_PREFIX = "sha256="
DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_RETRIES = 3
DEFAULT_BACKOFF_SECONDS = (0.5, 1.0, 2.0)


def serialize_body(event: Mapping[str, Any]) -> bytes:
    """Serialise the event once into the exact bytes that are signed and sent."""
    return json.dumps(event, separators=(",", ":")).encode("utf-8")


def sign(secret: str, timestamp: int | str, body: bytes) -> str:
    """Lowercase hex HMAC-SHA256 of ``"<timestamp>." + body``."""
    message = f"{timestamp}.".encode() + body
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def build_headers(secret: str, timestamp: int, body: bytes) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "X-Odoo-Timestamp": str(timestamp),
        "X-Odoo-Signature": SIGNATURE_PREFIX + sign(secret, timestamp, body),
    }


def build_event(
    event_type: str,
    model: str,
    record_id: int,
    payload: Mapping[str, Any],
    *,
    event_id: str | None = None,
    occurred_at: datetime | None = None,
) -> dict[str, Any]:
    """Event document expected by the connector (``WebhookEventIn``)."""
    moment = occurred_at or datetime.now(timezone.utc)  # noqa: UP017 (Odoo 17 runs Python 3.10)
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "event_type": event_type,
        "model": model,
        "record_id": record_id,
        "occurred_at": moment.isoformat(),
        "payload": dict(payload),
    }


@dataclass(frozen=True)
class DeliveryResult:
    ok: bool
    attempts: int
    status_code: int | None


def _is_retryable(status_code: int) -> bool:
    # 5xx means the connector (or a proxy) failed: the event may be delivered later. Every other
    # non-2xx (401 bad signature, 413 too large, 422 invalid payload, ...) will fail identically.
    return status_code >= 500


def deliver(
    post: Callable[..., Any],
    url: str,
    secret: str,
    body: bytes,
    *,
    retries: int = DEFAULT_RETRIES,
    backoff: tuple[float, ...] = DEFAULT_BACKOFF_SECONDS,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.time,
) -> DeliveryResult:
    """POST ``body`` signed for the connector, retrying transient failures.

    Retries (up to ``retries`` times, sleeping ``backoff[i]`` before retry ``i``) on transport
    errors and 5xx responses; never on other statuses. Every attempt reuses the same ``body`` (so
    the same ``event_id``, which the connector deduplicates) with a FRESH timestamp and signature,
    so a retry never falls outside the connector's replay window. Only exception *types* are
    logged: messages could echo the URL or other sensitive text; the secret is never logged.
    """
    attempts = 0
    status_code: int | None = None
    while True:
        attempts += 1
        headers = build_headers(secret, int(now()), body)
        try:
            response = post(url, data=body, headers=headers, timeout=timeout)
            status_code = int(response.status_code)
        except Exception as exc:  # any transport failure is retryable
            status_code = None
            _logger.warning(
                "connector webhook attempt %s failed (%s)", attempts, type(exc).__name__
            )
        else:
            if 200 <= status_code < 300:
                return DeliveryResult(True, attempts, status_code)
            _logger.warning("connector webhook attempt %s answered HTTP %s", attempts, status_code)
            if not _is_retryable(status_code):
                return DeliveryResult(False, attempts, status_code)
        if attempts > retries:
            return DeliveryResult(False, attempts, status_code)
        sleep(backoff[min(attempts - 1, len(backoff) - 1)] if backoff else 0.0)
