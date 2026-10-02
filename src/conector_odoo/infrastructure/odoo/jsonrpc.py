"""JSON-RPC transport (``POST {url}/jsonrpc``) built on a shared ``httpx.AsyncClient``."""

import asyncio
import itertools
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from conector_odoo.domain.errors import OdooAuthError, OdooUnavailable
from conector_odoo.infrastructure.odoo.errors import (
    map_http_status,
    map_jsonrpc_error,
    sanitize,
)
from conector_odoo.infrastructure.odoo.retry import is_idempotent, run_with_retry

logger = logging.getLogger(__name__)

Sleep = Callable[[float], Awaitable[None]]


class JsonRpcTransport:
    def __init__(
        self,
        url: str,
        db: str,
        user: str,
        api_key: str,
        *,
        timeout: float = 10.0,
        max_retries: int = 2,
        client: httpx.AsyncClient | None = None,
        sleep: Sleep = asyncio.sleep,
        backoff_base: float = 0.5,
    ) -> None:
        self._endpoint = f"{url.rstrip('/')}/jsonrpc"
        self._db = db
        self._user = user
        self._api_key = api_key
        self._timeout = timeout
        self._max_retries = max_retries
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._sleep = sleep
        self._backoff_base = backoff_base
        self._uid: int | None = None
        self._ids = itertools.count(1)

    async def authenticate(self) -> int:
        result = await self._call(
            "common", "authenticate", [self._db, self._user, self._api_key, {}], idempotent=True
        )
        if not isinstance(result, int) or isinstance(result, bool) or result <= 0:
            self._uid = None
            raise OdooAuthError("Odoo rejected the credentials")
        self._uid = result
        return result

    async def execute_kw(
        self,
        model: str,
        method: str,
        args: list[Any],
        kwargs: dict[str, Any] | None = None,
    ) -> Any:
        uid = self._uid if self._uid is not None else await self.authenticate()
        return await self._call(
            "object",
            "execute_kw",
            [self._db, uid, self._api_key, model, method, args, kwargs or {}],
            idempotent=is_idempotent(method),
            description=f"{model}.{method}",
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _call(
        self,
        service: str,
        method: str,
        args: list[Any],
        *,
        idempotent: bool,
        description: str | None = None,
    ) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {"service": service, "method": method, "args": args},
            "id": next(self._ids),
        }

        async def post() -> httpx.Response:
            return await self._client.post(self._endpoint, json=payload, timeout=self._timeout)

        label = description or f"{service}.{method}"
        try:
            response = await run_with_retry(
                post,
                idempotent=idempotent,
                max_retries=self._max_retries,
                retry_on=(httpx.TransportError,),
                sleep=self._sleep,
                base_delay=self._backoff_base,
                description=label,
            )
        except httpx.TransportError as exc:
            logger.error(
                "odoo unreachable", extra={"operation": label, "error": type(exc).__name__}
            )
            suffix = "" if idempotent else " (outcome unknown, not retried)"
            raise OdooUnavailable(f"cannot reach Odoo: {type(exc).__name__}{suffix}") from exc

        secrets = [self._api_key]
        if response.status_code >= 400:
            raise map_http_status(response.status_code, secrets)
        try:
            body = response.json()
        except ValueError as exc:
            raise OdooUnavailable("Odoo returned a non-JSON response") from exc
        if not isinstance(body, dict):
            raise OdooUnavailable("Odoo returned an unexpected response")
        if "error" in body:
            error = body["error"]
            if isinstance(error, dict):
                raise map_jsonrpc_error(error, secrets)
            raise OdooUnavailable(sanitize(str(error), secrets))
        return body.get("result")
