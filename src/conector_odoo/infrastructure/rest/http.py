"""HTTP engine of the REST adapter: auth, client-side rate limit, transport-only retries and
error normalization. Retries happen ONLY on httpx transport errors (never on HTTP statuses), and
never for a non-idempotent request unless an idempotency key was sent."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import httpx

from conector_odoo.domain.errors import RemoteUnavailable
from conector_odoo.infrastructure.rest.auth import Authenticator
from conector_odoo.infrastructure.rest.errors import error_for

logger = logging.getLogger(__name__)

_IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})
Sleep = Callable[[float], Awaitable[None]]


class RateLimiter:
    """Guarantees at least ``min_interval`` seconds between consecutive calls to ``wait``."""

    def __init__(
        self,
        min_interval: float = 0.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None
        self._lock = asyncio.Lock()

    @classmethod
    def per_second(
        cls,
        max_rps: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Sleep = asyncio.sleep,
    ) -> "RateLimiter":
        return cls(1.0 / max_rps, clock, sleep)

    async def wait(self) -> None:
        async with self._lock:
            now = self._clock()
            if self._last is not None and now < self._last + self._interval:
                ready = self._last + self._interval
                await self._sleep(ready - now)
                now = ready
            self._last = now


class RestHttpClient:
    def __init__(
        self,
        base_url: str,
        auth: Authenticator,
        *,
        extra_headers: Mapping[str, str] | None = None,
        tls_verify: bool = True,
        timeout: float = 30.0,
        max_retries: int = 2,
        backoff_base: float = 0.5,
        min_interval: float = 0.0,
        idempotency_header: str = "Idempotency-Key",
        clock: Callable[[], float] = time.monotonic,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._base_url = base_url.strip().rstrip("/")
        self._auth = auth
        self._extra_headers = dict(extra_headers or {})
        self._max_retries = max(max_retries, 0)
        self._backoff_base = backoff_base
        self._idempotency_header = idempotency_header
        self._sleep = sleep
        self._limiter = RateLimiter(min_interval, clock, sleep)
        self._client = httpx.AsyncClient(verify=tls_verify, timeout=timeout)

    def __repr__(self) -> str:
        return f"RestHttpClient(base_url={self._base_url!r})"

    async def aclose(self) -> None:
        await self._client.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        idempotency_key: str | None = None,
    ) -> httpx.Response:
        """Send the request; returns a 2xx response or raises a normalized domain error."""
        where = f"{method} {path}"
        refreshed = False
        while True:
            response = await self._send(method, path, params, json, idempotency_key, where)
            if response.status_code == 401 and self._auth.can_refresh and not refreshed:
                refreshed = True
                await self._auth.invalidate()
                continue
            if response.is_success:
                return response
            raise error_for(response, where, self._auth.secret_values())

    async def _send(
        self,
        method: str,
        path: str,
        params: Mapping[str, Any] | None,
        json: Any,
        idempotency_key: str | None,
        where: str,
    ) -> httpx.Response:
        retryable = method.upper() in _IDEMPOTENT_METHODS or idempotency_key is not None
        attempts = self._max_retries + 1 if retryable else 1
        for attempt in range(attempts):
            await self._limiter.wait()
            headers = dict(self._extra_headers)
            headers.update(await self._auth.headers(self._client))
            if idempotency_key is not None:
                headers[self._idempotency_header] = idempotency_key
            try:
                response = await self._client.request(
                    method,
                    self._base_url + "/" + path.lstrip("/"),
                    params=params,
                    json=json,
                    headers=headers,
                )
            except (httpx.InvalidURL, httpx.UnsupportedProtocol, UnicodeError) as exc:
                # A request that cannot even be built is a configuration problem of the target
                # (bad base URL, path or header), not a record problem: report it as
                # RemoteUnavailable, never retry it and never echo the exception text (it may
                # contain the URL or header values).
                logger.debug("%s rejected before sending: %s", where, type(exc).__name__)
                raise RemoteUnavailable(
                    f"{where}: invalid request URL or headers ({type(exc).__name__}); "
                    "check the profile base URL, the resource path and the extra headers"
                ) from None
            except httpx.TransportError as exc:
                logger.debug("%s failed on attempt %d: %s", where, attempt + 1, type(exc).__name__)
                if attempt + 1 >= attempts:
                    raise RemoteUnavailable(
                        f"{where}: {type(exc).__name__} after {attempt + 1} attempt(s)"
                    ) from None
                await self._sleep(self._backoff_base * 2**attempt)
                continue
            logger.debug("%s -> HTTP %d", where, response.status_code)
            return response
        raise AssertionError("unreachable")  # pragma: no cover
