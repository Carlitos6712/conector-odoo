"""``Idempotency-Key`` support for POST routes, as a per-request guard dependency.

The guard is a dependency (not middleware) so request/response bodies are never buffered
globally: each handler passes the validated body and the action to run, and gets a ``Response``
back. The HTTP contract is documented on ``IdempotencyGuard``.
"""

import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import Depends, Header, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from conector_odoo.domain.errors import (
    ConnectorError,
    CreatedButUnreadable,
    OdooAuthError,
    OdooNotFound,
    OdooPermissionError,
    OdooValidationError,
)
from conector_odoo.infrastructure.api.dependencies import get_container
from conector_odoo.infrastructure.api.errors import (
    connector_error_response,
    created_but_unreadable_response,
)
from conector_odoo.infrastructure.api.schemas import ErrorOut
from conector_odoo.infrastructure.idempotency.store import IdempotencyRecord, IdempotencyStore

logger = logging.getLogger(__name__)

MAX_KEY_LENGTH = 255
REPLAYED_HEADER = "Idempotent-Replayed"

# Errors that guarantee Odoo did not apply the write: the key can be released for a retry.
_NO_WRITE_ERRORS = (OdooValidationError, OdooNotFound, OdooAuthError, OdooPermissionError)

# OpenAPI documentation shared by the POST routes that accept ``Idempotency-Key``.
IDEMPOTENCY_RESPONSES: dict[int | str, dict[str, Any]] = {
    202: {"description": "Created in Odoo but could not be read back; see the Location header."},
    409: {
        "model": ErrorOut,
        "description": "The Idempotency-Key is in progress, or its previous outcome is unknown.",
    },
    422: {"model": ErrorOut, "description": "Invalid input or Idempotency-Key reused."},
    503: {"model": ErrorOut, "description": "The idempotency store is unavailable."},
}


def get_idempotency_store(request: Request) -> IdempotencyStore:
    store: IdempotencyStore = get_container(request).idempotency
    return store


def request_hash(request: Request, payload: BaseModel | None) -> str:
    canonical = json.dumps(
        {
            "body": payload.model_dump(mode="json") if payload is not None else None,
            "path_params": request.path_params,
            "query": sorted(request.query_params.multi_items()),
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _error(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse({"error": code, "detail": detail}, status_code=status)


class IdempotencyGuard:
    """Runs a POST action at most once per ``Idempotency-Key``.

    HTTP contract:

    * The ``Idempotency-Key`` header is optional on ``POST /customers``, ``POST /sale-orders`` and
      ``POST /sale-orders/{id}/confirm`` (at most ``MAX_KEY_LENGTH`` characters, otherwise 422).
      Without it the request is simply executed.
    * The key is scoped by ``"METHOD path"``: the same key on another endpoint is independent.
    * The request hash is the SHA-256 of the canonical JSON of the validated body, path params and
      query params. Same key, different hash: 422 ``idempotency_key_reused``.
    * First request: the key is claimed (``in_progress``). On 2xx, including the
      ``202 created_but_unreadable`` answer (the record exists in Odoo), the response is stored and
      replayed to later identical requests with ``Idempotent-Replayed: true``.
    * Errors that guarantee no write happened (validation, not found, auth, permission) release
      the key so the client may retry with it.
    * Errors where the write may have been applied (``OdooUnavailable``: timeout, network, 5xx;
      any unexpected exception) mark the key ``unknown``: a retry with the same key and body gets
      409 ``idempotency_outcome_unknown``; verify in Odoo and use a new key. Cancellation leaves the
      key ``in_progress`` (409 ``idempotency_in_progress``); once older than
      ``idempotency_in_progress_timeout_seconds`` it is reported as ``unknown`` too.
    * ``unknown``/stale keys are never silently re-run; they disappear when purged
      (``idempotency_ttl_hours``).
    * If the store itself fails before the action runs: 503 ``idempotency_store_unavailable`` and
      the action is not executed. If storing the final response fails, the original response is
      still returned and the key stays ``in_progress`` (then ``unknown``).
    """

    def __init__(self, request: Request, store: IdempotencyStore, key: str | None) -> None:
        self._request = request
        self._store = store
        self._key = key
        self._scope = f"{request.method} {request.url.path}"

    async def run(
        self,
        payload: BaseModel | None,
        action: Callable[[], Awaitable[BaseModel]],
        status_code: int,
    ) -> Response:
        """Run ``action`` once per ``Idempotency-Key``; plain execution when no key was sent."""
        if self._key is None:
            return await self._execute(action, status_code)
        digest = request_hash(self._request, payload)
        try:
            existing = await self._store.begin(self._key, self._scope, digest)
        except Exception:
            logger.exception("idempotency store unavailable; request not executed")
            return _error(
                503,
                "idempotency_store_unavailable",
                "the idempotency store is unavailable; retry later",
            )
        if existing is not None:
            return self._replay_or_reject(existing, digest)
        try:
            response = await self._execute(action, status_code)
        except _NO_WRITE_ERRORS:
            await self._release()
            raise
        except ConnectorError as exc:
            response = connector_error_response(self._request, exc)
            await self._mark_unknown(response)
            return response
        except Exception:
            await self._mark_unknown(None)
            raise
        # CancelledError is deliberately not caught: the write may have happened, so the key
        # stays ``in_progress`` (409, then ``unknown`` once stale) rather than allowing a duplicate.
        await self._finish(response)
        return response

    def _replay_or_reject(self, existing: IdempotencyRecord, digest: str) -> Response:
        if existing.request_hash != digest:
            return _error(
                422,
                "idempotency_key_reused",
                "this Idempotency-Key was already used with a different request",
            )
        if existing.status == "unknown":
            return _error(
                409,
                "idempotency_outcome_unknown",
                "previous attempt may have been applied; verify before retrying with a new key",
            )
        if existing.status == "in_progress" or existing.response_body is None:
            return _error(
                409,
                "idempotency_in_progress",
                "a request with this Idempotency-Key is still being processed",
            )
        return Response(
            existing.response_body,
            status_code=existing.response_status or 200,
            media_type="application/json",
            headers={**existing.response_headers, REPLAYED_HEADER: "true"},
        )

    async def _execute(
        self, action: Callable[[], Awaitable[BaseModel]], status_code: int
    ) -> Response:
        try:
            result = await action()
        except CreatedButUnreadable as exc:
            return created_but_unreadable_response(self._request, exc)
        return JSONResponse(result.model_dump(mode="json"), status_code=status_code)

    async def _release(self) -> None:
        assert self._key is not None
        try:
            await self._store.release(self._key, self._scope)
        except Exception:
            logger.exception("could not release the idempotency key; it stays in progress")

    async def _mark_unknown(self, response: Response | None) -> None:
        assert self._key is not None
        try:
            await self._store.mark_unknown(
                self._key,
                self._scope,
                response.status_code if response is not None else None,
                bytes(response.body).decode() if response is not None else None,
                # Error responses are never replayed (a retry gets 409 ``outcome_unknown``), so
                # there is nothing to restore from headers: none are stored.
                response_headers={},
            )
        except Exception:
            logger.exception("could not mark the idempotency key unknown; it stays in progress")

    async def _finish(self, response: Response) -> None:
        assert self._key is not None
        headers = {k: v for k, v in response.headers.items() if k.lower() == "location"}
        try:
            await self._store.complete(
                self._key, self._scope, response.status_code, bytes(response.body).decode(), headers
            )
        except Exception:
            logger.exception("could not store the idempotent response; key left in progress")


def get_idempotency_guard(
    request: Request,
    store: Annotated[IdempotencyStore, Depends(get_idempotency_store)],
    idempotency_key: Annotated[str | None, Header(min_length=1, max_length=MAX_KEY_LENGTH)] = None,
) -> IdempotencyGuard:
    return IdempotencyGuard(request, store, idempotency_key)


GuardDep = Annotated[IdempotencyGuard, Depends(get_idempotency_guard)]
