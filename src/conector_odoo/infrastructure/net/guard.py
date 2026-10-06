"""Enforce the outbound URL policy where connections are made.

Checking a URL and connecting to it are two lookups of the same name, so a DNS answer that changes
in between (DNS rebinding) would defeat a check done up front. These classes close that gap by
doing the check INSIDE the connection step:

* ``GuardedBackend`` is an httpcore network backend. For every new TCP connection it resolves the
  host once, validates EVERY returned address against the policy and then connects to one of the
  validated addresses by IP. There is no second lookup. httpcore still passes the original host
  name to the TLS layer, so SNI and certificate verification use the name, and the ``Host`` header
  is untouched.
* ``GuardedTransport`` is an ``httpx`` transport built on that backend, plus a no-DNS pre-check
  (scheme, literal IPs). It works at the connection level, so a keep-alive connection that was
  validated when it was opened stays pinned to that address.
* ``connect_guarded`` does the same for the blocking ``socket`` world (XML-RPC).

Clients built here ignore proxy environment variables: a proxy resolves the target itself and
would bypass the policy.
"""

import asyncio
import ipaddress
import socket
import ssl
from collections.abc import Iterable
from typing import Any

import httpcore
import httpx
from httpcore import AnyIOBackend, AsyncNetworkBackend, AsyncNetworkStream

from conector_odoo.domain.errors import OutboundUrlBlocked
from conector_odoo.domain.outbound import OutboundPolicy

_DEFAULT_LIMITS = httpx.Limits(max_connections=100, max_keepalive_connections=20)


async def resolve_host(host: str, port: int) -> list[str]:
    """Every address ``host`` resolves to, in resolver order, without duplicates. Looked up by
    name at call time so tests can substitute it."""
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


def resolve_host_blocking(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


def _literal(host: str) -> str | None:
    try:
        return str(ipaddress.ip_address(host.strip().strip("[]")))
    except ValueError:
        return None


class GuardedBackend(AsyncNetworkBackend):
    def __init__(self, policy: OutboundPolicy, inner: AsyncNetworkBackend | None = None) -> None:
        self._policy = policy
        self._inner = inner or AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,  # noqa: ASYNC109 - httpcore backend interface
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> AsyncNetworkStream:
        literal = _literal(host)
        if literal is not None:
            addresses = [literal]
        else:
            try:
                addresses = await asyncio.wait_for(resolve_host(host, port), timeout)
            except TimeoutError:
                raise httpcore.ConnectTimeout("name resolution timed out") from None
            except OSError as exc:
                raise httpcore.ConnectError(str(exc)) from None
        self._policy.check_addresses(host, addresses)
        last: Exception | None = None
        for address in addresses:
            try:
                return await self._inner.connect_tcp(
                    address,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last = exc
        assert last is not None  # check_addresses refuses an empty answer
        raise last

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,  # noqa: ASYNC109 - httpcore backend interface
        socket_options: Iterable[Any] | None = None,
    ) -> AsyncNetworkStream:
        raise OutboundUrlBlocked("outbound request blocked by the URL policy: unix sockets")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


class GuardedTransport(httpx.AsyncHTTPTransport):
    def __init__(
        self,
        policy: OutboundPolicy,
        *,
        verify: ssl.SSLContext | str | bool = True,
        limits: httpx.Limits = _DEFAULT_LIMITS,
    ) -> None:
        super().__init__(verify=verify, limits=limits)
        self._policy = policy
        # httpx offers no public hook for the network backend, so the pool it just built (idle, no
        # sockets yet) is replaced by an equivalent one that uses the guarded backend. Covered by
        # tests/net: if a future httpx changes this, they fail instead of silently unguarding.
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=httpx.create_ssl_context(verify=verify),
            max_connections=limits.max_connections,
            max_keepalive_connections=limits.max_keepalive_connections,
            keepalive_expiry=limits.keepalive_expiry,
            network_backend=GuardedBackend(policy),
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.scheme not in ("http", "https"):
            # What httpx itself raises, so callers keep their existing "bad URL" handling.
            raise httpx.UnsupportedProtocol(
                f"Request URL has an unsupported protocol '{request.url.scheme}://'."
            )
        self._policy.check_url(str(request.url))
        return await super().handle_async_request(request)


def guarded_client(
    policy: OutboundPolicy,
    *,
    verify: bool = True,
    timeout: float | httpx.Timeout | None = 30.0,
    limits: httpx.Limits | None = None,
    headers: dict[str, str] | None = None,
    follow_redirects: bool = False,
) -> httpx.AsyncClient:
    """An ``AsyncClient`` whose every connection obeys ``policy`` (see the module docstring)."""
    return httpx.AsyncClient(
        verify=verify,  # the transport owns TLS; passed too so the setting stays observable
        transport=GuardedTransport(policy, verify=verify, limits=limits or _DEFAULT_LIMITS),
        timeout=timeout,
        headers=headers,
        follow_redirects=follow_redirects,
        trust_env=False,
    )


def connect_guarded(
    policy: OutboundPolicy,
    host: str,
    port: int,
    timeout: float | None = None,
    source_address: tuple[str, int] | None = None,
) -> socket.socket:
    """Blocking twin of ``GuardedBackend.connect_tcp``: resolve, validate all, connect by IP."""
    literal = _literal(host)
    addresses = [literal] if literal is not None else resolve_host_blocking(host, port)
    policy.check_addresses(host, addresses)
    last: OSError | None = None
    for address in addresses:
        try:
            return socket.create_connection((address, port), timeout, source_address)
        except OSError as exc:
            last = exc
    assert last is not None
    raise last
