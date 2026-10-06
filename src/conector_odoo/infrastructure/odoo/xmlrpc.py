"""XML-RPC transport (``/xmlrpc/2/common`` and ``/xmlrpc/2/object``).

``xmlrpc.client`` is blocking, so every call runs through ``asyncio.to_thread``. A fresh
``ServerProxy`` is created per call because proxies are not thread-safe.
"""

import asyncio
import http.client
import logging
import xmlrpc.client
from collections.abc import Awaitable, Callable
from typing import Any
from xml.parsers.expat import ExpatError
from xmlrpc.client import ServerProxy

from conector_odoo.domain.errors import OdooAuthError, OdooUnavailable
from conector_odoo.domain.outbound import OutboundPolicy
from conector_odoo.infrastructure.net.guard import connect_guarded
from conector_odoo.infrastructure.odoo.errors import map_http_status, map_xmlrpc_fault
from conector_odoo.infrastructure.odoo.retry import is_idempotent, run_with_retry

logger = logging.getLogger(__name__)

Sleep = Callable[[float], Awaitable[None]]


def _guard(connection: Any, policy: OutboundPolicy | None) -> None:
    """Route the connection's TCP connect through the outbound policy (resolve, validate every
    address, connect by IP; TLS still verifies the original host name). ``_create_connection`` is
    the attribute ``http.client`` itself uses for this; tests/net fails if it ever goes away."""
    if policy is not None:
        connection._create_connection = lambda address, timeout, source=None: connect_guarded(
            policy, address[0], address[1], timeout, source
        )


class _TimeoutTransport(xmlrpc.client.Transport):
    def __init__(self, timeout: float, policy: OutboundPolicy | None = None) -> None:
        super().__init__()
        self._timeout = timeout
        self._policy = policy

    def make_connection(self, host: Any) -> Any:
        connection = super().make_connection(host)
        connection.timeout = self._timeout
        _guard(connection, self._policy)
        return connection


class _TimeoutSafeTransport(xmlrpc.client.SafeTransport):
    def __init__(self, timeout: float, policy: OutboundPolicy | None = None) -> None:
        super().__init__()
        self._timeout = timeout
        self._policy = policy

    def make_connection(self, host: Any) -> Any:
        connection = super().make_connection(host)
        connection.timeout = self._timeout
        _guard(connection, self._policy)
        return connection


class XmlRpcTransport:
    def __init__(
        self,
        url: str,
        db: str,
        user: str,
        api_key: str,
        *,
        timeout: float = 10.0,
        max_retries: int = 2,
        policy: OutboundPolicy | None = None,
        sleep: Sleep = asyncio.sleep,
        backoff_base: float = 0.5,
    ) -> None:
        self._base = url.rstrip("/")
        self._db = db
        self._user = user
        self._api_key = api_key
        self._timeout = timeout
        self._max_retries = max_retries
        self._policy = policy
        self._sleep = sleep
        self._backoff_base = backoff_base
        self._uid: int | None = None

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
        return None

    def _proxy(self, endpoint: str) -> Any:
        url = f"{self._base}/xmlrpc/2/{endpoint}"
        transport: xmlrpc.client.Transport
        if url.startswith("https"):
            transport = _TimeoutSafeTransport(self._timeout, self._policy)
        else:
            transport = _TimeoutTransport(self._timeout, self._policy)
        return ServerProxy(url, transport=transport, allow_none=True)

    def _blocking_call(self, endpoint: str, method: str, args: list[Any]) -> Any:
        proxy = self._proxy(endpoint)
        return getattr(proxy, method)(*args)

    async def _call(
        self,
        endpoint: str,
        method: str,
        args: list[Any],
        *,
        idempotent: bool,
        description: str | None = None,
    ) -> Any:
        label = description or f"{endpoint}.{method}"
        secrets = [self._api_key]

        async def invoke() -> Any:
            return await asyncio.to_thread(self._blocking_call, endpoint, method, args)

        try:
            return await run_with_retry(
                invoke,
                idempotent=idempotent,
                max_retries=self._max_retries,
                retry_on=(OSError,),
                sleep=self._sleep,
                base_delay=self._backoff_base,
                description=label,
            )
        except xmlrpc.client.Fault as exc:
            raise map_xmlrpc_fault(int(exc.faultCode), str(exc.faultString), secrets) from None
        except xmlrpc.client.ProtocolError as exc:
            raise map_http_status(exc.errcode, secrets) from None
        except OSError as exc:
            logger.error(
                "odoo unreachable", extra={"operation": label, "error": type(exc).__name__}
            )
            suffix = "" if idempotent else " (outcome unknown, not retried)"
            raise OdooUnavailable(f"cannot reach Odoo: {type(exc).__name__}{suffix}") from exc
        except (http.client.HTTPException, ExpatError) as exc:
            logger.error(
                "odoo invalid response", extra={"operation": label, "error": type(exc).__name__}
            )
            suffix = "" if idempotent else " (outcome unknown, not retried)"
            raise OdooUnavailable(f"invalid Odoo response: {type(exc).__name__}{suffix}") from exc
        except xmlrpc.client.Error as exc:
            raise OdooUnavailable(f"invalid XML-RPC response: {type(exc).__name__}") from exc
