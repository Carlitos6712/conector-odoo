"""JSON-2 transport for Odoo 19: ``POST {url}/json/2/{model}/{method}``.

Authentication is a bearer API key plus the ``X-Odoo-Database`` header; there is no uid and no
session. The body is a JSON object of *named* method arguments, whereas the ``OdooTransport``
protocol is positional (``execute_kw(model, method, args, kwargs)``). ``_to_body`` translates
the positional arguments for the methods the client uses:

=================  ============================  ===========================================
method             positional ``args``           named body
=================  ============================  ===========================================
search_read        ``[domain]``                  ``domain`` (+ fields, limit, offset, order)
search             ``[domain]``                  ``domain`` (+ limit, offset, order)
search_count       ``[domain]``                  ``domain``
read               ``[ids]``                     ``ids`` (+ fields)
create             ``[values]`` or ``[list]``    ``vals_list`` (always a list; returns ids)
write              ``[ids, values]``             ``ids``, ``vals``
action_confirm     ``[ids]``                     ``ids``
=================  ============================  ===========================================

Remaining ``kwargs`` (``context`` included) are forwarded as named arguments. Any other method
is refused with ``OdooUnavailable`` before a request is made (the positional order of its
parameters is unknown here), so add a translation before using a new method over json2.

``authenticate`` has no uid concept in JSON-2 (no session), so it proves two things:

1. the key's own identity: ``POST res.users/context_get`` runs as the key's owner and (in the
   Odoo versions we know) includes the owner's ``uid`` in the returned context dict;
2. the configured login's id: ``POST res.users/search`` on ``[["login", "=", user]]``.

The key is accepted only if both agree; a different owner or no such login raises
``OdooAuthError``. This replaces the previous check, which accepted any key able to read
``res.users``. UNCERTAINTY: the ``uid`` entry of the ``context_get`` response is not documented
for Odoo 19. If it is absent or not an integer, ownership cannot be verified, so a warning is
logged and the login lookup alone decides (the key is still validated by the HTTP 401 check
and the lookup needs read access to ``res.users``). Any non-auth failure of ``context_get``
(403/404/5xx) is handled the same way (warning + fallback); only a 401 aborts.
Verify against a real Odoo 19 instance.
The returned id is always positive, so it cannot be confused with the "authentication failed"
values (0/False) of the other protocols.

Errors: JSON-2 answers with an HTTP status and ``{"name": "odoo.exceptions.X", "message": ...}``.
401 -> ``OdooAuthError``; 403 -> ``OdooPermissionError``; other errors reuse
``map_odoo_exception`` on ``name`` (MissingError -> not found, ValidationError/UserError ->
validation); unknown names, bodies without a name and 5xx -> ``OdooUnavailable``.
Retry policy matches JSON-RPC: network errors only, idempotent methods only.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from conector_odoo.domain.errors import ConnectorError, OdooAuthError, OdooUnavailable
from conector_odoo.infrastructure.odoo.errors import (
    map_http_status,
    map_odoo_exception,
    sanitize,
)
from conector_odoo.infrastructure.odoo.retry import is_idempotent, run_with_retry

logger = logging.getLogger(__name__)

Sleep = Callable[[float], Awaitable[None]]


def _limits(max_connections: int | None) -> httpx.Limits:
    """Connection pool sized to the client's concurrency cap (httpx defaults when unset)."""
    if max_connections is None:
        return httpx.Limits(max_connections=100, max_keepalive_connections=20)
    return httpx.Limits(max_connections=max_connections, max_keepalive_connections=max_connections)


# Positional parameter names per method (before any keyword arguments).
_POSITIONAL: dict[str, tuple[str, ...]] = {
    "search_read": ("domain",),
    "search": ("domain",),
    "search_count": ("domain",),
    "read": ("ids",),
    "write": ("ids", "vals"),
    "action_confirm": ("ids",),
}


def _to_body(method: str, args: list[Any], kwargs: dict[str, Any] | None) -> dict[str, Any]:
    body: dict[str, Any] = dict(kwargs or {})
    if method == "create":
        if len(args) != 1:
            raise OdooUnavailable("json2 create expects a single values argument")
        first = args[0]
        body["vals_list"] = list(first) if isinstance(first, list) else [first]
        return body
    names = _POSITIONAL.get(method)
    if names is None:
        raise OdooUnavailable(f"json2 transport does not support method {method!r}")
    if len(args) > len(names):
        raise OdooUnavailable(f"too many positional arguments for json2 {method}")
    for name, value in zip(names, args, strict=False):
        body[name] = value
    return body


def _is_id(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


class Json2Transport:
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
        max_connections: int | None = None,
        sleep: Sleep = asyncio.sleep,
        backoff_base: float = 0.5,
    ) -> None:
        self._base = f"{url.rstrip('/')}/json/2"
        self._db = db
        self._user = user
        self._api_key = api_key
        self._timeout = timeout
        self._max_retries = max_retries
        self._owns_client = client is None
        self._max_connections = max_connections
        self._client = client or httpx.AsyncClient(timeout=timeout, limits=_limits(max_connections))
        self._sleep = sleep
        self._backoff_base = backoff_base
        self._uid: int | None = None

    async def authenticate(self) -> int:
        self._uid = None
        owner = await self._key_owner()
        found = await self._call(
            "res.users",
            "search",
            {"domain": [["login", "=", self._user]], "limit": 1},
            idempotent=True,
        )
        if not isinstance(found, list) or not found or not _is_id(found[0]):
            raise OdooAuthError("Odoo rejected the credentials")
        uid = int(found[0])
        if _is_id(owner):
            if owner != uid:
                raise OdooAuthError("the API key does not belong to the configured user")
        else:
            logger.warning(
                "json2 could not verify the API key owner: context_get returned no usable uid",
                extra={"operation": "res.users.context_get"},
            )
        self._uid = uid
        return uid

    async def _key_owner(self) -> object:
        """Best-effort ``uid`` of the API key owner; ``None`` when it cannot be determined.

        Auth failures (401) still propagate. Any other failure of ``context_get`` (it is not
        documented for every Odoo version, and may be forbidden) only skips the owner check and
        falls back to the login lookup.
        """
        try:
            context = await self._call("res.users", "context_get", {}, idempotent=True)
        except OdooAuthError:
            raise
        except ConnectorError as exc:
            logger.warning(
                "json2 could not verify the API key owner: context_get failed",
                extra={"operation": "res.users.context_get", "error_type": type(exc).__name__},
            )
            return None
        return context.get("uid") if isinstance(context, dict) else None

    async def execute_kw(
        self,
        model: str,
        method: str,
        args: list[Any],
        kwargs: dict[str, Any] | None = None,
    ) -> Any:
        body = _to_body(method, args, kwargs)
        return await self._call(model, method, body, idempotent=is_idempotent(method))

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _call(
        self, model: str, method: str, body: dict[str, Any], *, idempotent: bool
    ) -> Any:
        url = f"{self._base}/{model}/{method}"
        headers = {
            "Authorization": f"bearer {self._api_key}",
            "X-Odoo-Database": self._db,
            "Content-Type": "application/json; charset=utf-8",
        }

        async def post() -> httpx.Response:
            return await self._client.post(url, json=body, headers=headers, timeout=self._timeout)

        label = f"{model}.{method}"
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
            raise self._map_error(response, secrets)
        try:
            return response.json()
        except ValueError as exc:
            raise OdooUnavailable("Odoo returned a non-JSON response") from exc

    @staticmethod
    def _map_error(response: httpx.Response, secrets: list[str]) -> Exception:
        status = response.status_code
        if status in {401, 403}:
            return map_http_status(status, secrets)
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict) and isinstance(payload.get("name"), str):
            message = sanitize(str(payload.get("message") or "Odoo error"), secrets)
            return map_odoo_exception(payload["name"], message)
        return map_http_status(status, secrets)
