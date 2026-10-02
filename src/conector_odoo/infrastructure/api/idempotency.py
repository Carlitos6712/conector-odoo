"""``Idempotency-Key`` support for POST routes, as a per-request guard dependency.

The guard is a dependency (not middleware) so request/response bodies are never buffered
globally: each handler passes the validated body and the action to run, and gets a ``Response``
back. See ``infrastructure.idempotency.sqlite_store`` for the full semantics.
"""

import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import Depends, Header, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from conector_odoo.domain.errors import CreatedButUnreadable
from conector_odoo.infrastructure.api.dependencies import get_container
from conector_odoo.infrastructure.api.errors import created_but_unreadable_response
from conector_odoo.infrastructure.api.schemas import ErrorOut
from conector_odoo.infrastructure.idempotency.store import IdempotencyStore

logger = logging.getLogger(__name__)

MAX_KEY_LENGTH = 255
REPLAYED_HEADER = "Idempotent-Replayed"

# OpenAPI documentation shared by the POST routes that accept ``Idempotency-Key``.
IDEMPOTENCY_RESPONSES: dict[int | str, dict[str, Any]] = {
    202: {"description": "Created in Odoo but could not be read back; see the Location header."},
    409: {"model": ErrorOut, "description": "A request with this Idempotency-Key is in progress."},
    422: {"model": ErrorOut, "description": "Invalid input or Idempotency-Key reused."},
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
        existing = await self._store.begin(self._key, self._scope, digest)
        if existing is not None:
            if existing.request_hash != digest:
                return _error(
                    422,
                    "idempotency_key_reused",
                    "this Idempotency-Key was already used with a different request",
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
        try:
            response = await self._execute(action, status_code)
        except Exception:
            await self._store.release(self._key, self._scope)
            raise
        # CancelledError is deliberately not released: the write may have happened, so the key
        # stays ``in_progress`` (409) until purged rather than allowing a duplicate.
        await self._finish(response)
        return response

    async def _execute(
        self, action: Callable[[], Awaitable[BaseModel]], status_code: int
    ) -> Response:
        try:
            result = await action()
        except CreatedButUnreadable as exc:
            return created_but_unreadable_response(self._request, exc)
        return JSONResponse(result.model_dump(mode="json"), status_code=status_code)

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
