"""``POST /webhooks/odoo``: signed events pushed by Odoo (addon in ``odoo_addon/``).

Authentication is the HMAC signature, NOT ``X-API-Key`` (Odoo cannot hold the connector key), so
this router is mounted without ``require_api_key``.

Signing scheme (the Odoo addon must match it exactly; implemented in
``infrastructure/webhooks/signature.py``)::

    X-Odoo-Timestamp: <unix seconds, ASCII digits>
    X-Odoo-Signature: sha256=<lowercase hex>        (bare hex is also accepted)

    signature = HMAC-SHA256(key=webhook_secret (UTF-8),
                            msg=f"{timestamp}.".encode() + raw_request_body).hexdigest()

The MAC is computed over the RAW body bytes exactly as sent, so the addon must sign the same bytes
it puts on the wire (do not re-serialise JSON after signing). Requests whose timestamp differs from
the server clock by more than ``webhook_tolerance_seconds`` are rejected, which bounds replays.

Processing order (cheapest and least-trusting checks first):

1. Body larger than 1 MiB -> 413 ``payload_too_large`` (checked from ``Content-Length`` and while
   streaming, so a chunked body cannot bypass it).
2. Missing/invalid headers, stale timestamp or bad signature -> 401 ``invalid_signature``.
3. Invalid JSON or schema (``WebhookEventIn``) -> 422 ``validation_error``.
4. Unknown ``event_type`` -> 202 ``{"status": "ignored"}`` and an INFO log "ignored unknown event"
   (acknowledged so Odoo does not retry; not dispatched, not deduplicated).
5. Dedup (two-phase, see ``infrastructure/webhooks/store.py``). The id is recorded only after
   authentication and validation, so forged or malformed requests cannot burn ids:

   * ``processed`` id -> 200 ``{"status": "duplicate"}``.
   * ``received`` id newer than ``webhook_redelivery_after_seconds`` -> 200 ``duplicate``
     (the first attempt may still be running).
   * ``received`` id older than that -> the previous attempt died or failed: dispatched again
     (``received_at`` refreshed), 202 ``accepted``.
6. New id (or a re-dispatch) -> 202 ``{"status": "accepted"}`` with the id stored as ``received``;
   a ``BackgroundTask`` publishes the event on the in-process bus after the response is sent and
   marks the id ``processed`` only when every handler succeeded.

Delivery to handlers is AT-LEAST-ONCE: a crash or a failing handler leaves the id ``received``,
so Odoo's next redelivery after the window runs the handlers again. Handlers MUST therefore be
idempotent. If the dedup store fails before dispatch the answer is 503 so Odoo retries.
"""

import logging
import time
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from conector_odoo.application.event_bus import InMemoryEventBus
from conector_odoo.application.events import HandleOdooEvent
from conector_odoo.config import Settings
from conector_odoo.domain.events import KNOWN_EVENT_TYPES, OdooEvent
from conector_odoo.infrastructure.api.dependencies import (
    get_event_bus,
    get_settings,
    get_webhook_event_store,
)
from conector_odoo.infrastructure.api.schemas import ErrorOut, WebhookAck, WebhookEventIn
from conector_odoo.infrastructure.webhooks.signature import verify
from conector_odoo.infrastructure.webhooks.store import SqliteWebhookEventStore

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 1024 * 1024
SIGNATURE_HEADER = "X-Odoo-Signature"
TIMESTAMP_HEADER = "X-Odoo-Timestamp"

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _error(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse({"error": code, "detail": detail}, status_code=status)


async def _read_body(request: Request) -> bytes | None:
    """Read the raw body, or ``None`` when it exceeds ``MAX_BODY_BYTES``."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        return None
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY_BYTES:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


async def _dispatch(
    handle: HandleOdooEvent, store: SqliteWebhookEventStore, event_id: str, event: OdooEvent
) -> None:
    """Run the handlers and mark the event ``processed`` only if all of them succeeded."""
    try:
        succeeded = await handle.execute(event)
    except Exception:
        logger.exception("webhook event dispatch failed", extra={"event_id": event_id})
        return
    if not succeeded:
        logger.warning(
            "webhook event left received; a redelivery will retry it", extra={"event_id": event_id}
        )
        return
    try:
        await store.mark_processed(event_id)
    except Exception:
        logger.exception("could not mark webhook event processed", extra={"event_id": event_id})


@router.post(
    "/odoo",
    status_code=202,
    response_model=WebhookAck,
    responses={
        200: {"model": WebhookAck, "description": "Duplicate delivery (processed or in flight)."},
        401: {"model": ErrorOut, "description": "Missing or invalid signature/timestamp."},
        413: {"model": ErrorOut, "description": "Body larger than 1 MiB."},
        422: {"model": ErrorOut, "description": "Invalid event payload."},
        503: {"model": ErrorOut, "description": "Event store unavailable; Odoo should retry."},
    },
)
async def receive_odoo_event(
    request: Request,
    background: BackgroundTasks,
    settings: Annotated[Settings, Depends(get_settings)],
    bus: Annotated[InMemoryEventBus, Depends(get_event_bus)],
    store: Annotated[SqliteWebhookEventStore, Depends(get_webhook_event_store)],
) -> Response:
    raw = await _read_body(request)
    if raw is None:
        logger.warning("webhook rejected", extra={"reason": "payload_too_large"})
        return _error(413, "payload_too_large", f"body exceeds {MAX_BODY_BYTES} bytes")

    timestamp = request.headers.get(TIMESTAMP_HEADER)
    signature = request.headers.get(SIGNATURE_HEADER)
    if (
        timestamp is None
        or signature is None
        or not verify(
            settings.webhook_secret.get_secret_value(),
            timestamp,
            raw,
            signature,
            time.time(),
            settings.webhook_tolerance_seconds,
        )
    ):
        reason = "missing_headers" if timestamp is None or signature is None else "bad_signature"
        logger.warning("webhook rejected", extra={"reason": reason})
        return _error(401, "invalid_signature", "missing, stale or invalid webhook signature")

    try:
        incoming = WebhookEventIn.model_validate_json(raw)
    except ValidationError as exc:
        # Only location and message: ``input`` would echo the (signed, but untrusted) payload.
        detail = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
        )
        return _error(422, "validation_error", detail)

    event_id = str(incoming.event_id)
    if incoming.event_type not in KNOWN_EVENT_TYPES:
        logger.info(
            "ignored unknown event",
            extra={"event_type": incoming.event_type, "event_id": event_id},
        )
        return JSONResponse({"status": "ignored", "event_id": event_id}, status_code=202)

    try:
        claim = await store.claim(
            event_id, redelivery_after_seconds=settings.webhook_redelivery_after_seconds
        )
    except Exception:
        logger.exception("webhook event store unavailable")
        return _error(503, "webhook_store_unavailable", "could not record the event; retry later")
    if claim == "duplicate":
        logger.info("duplicate webhook ignored", extra={"event_id": event_id})
        return JSONResponse({"status": "duplicate", "event_id": event_id}, status_code=200)
    if claim == "redeliver":
        logger.info("redelivered webhook re-dispatched", extra={"event_id": event_id})

    event = OdooEvent(
        event_type=incoming.event_type,
        model=incoming.model,
        record_id=incoming.record_id,
        payload=incoming.payload,
        occurred_at=incoming.occurred_at,
    )
    background.add_task(_dispatch, HandleOdooEvent(bus), store, event_id, event)
    return JSONResponse({"status": "accepted", "event_id": event_id}, status_code=202)
