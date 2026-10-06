import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import httpx
import pytest

from conector_odoo.domain.errors import OutboundUrlBlocked
from conector_odoo.domain.outbound import DEFAULT_POLICY, OutboundMode, OutboundPolicy
from conector_odoo.infrastructure.net import guard
from conector_odoo.infrastructure.net.guard import GuardedTransport, guarded_client

Answer = list[str]


@dataclass
class Origin:
    """A tiny HTTP/1.1 origin on 127.0.0.1 that records the Host header of each request."""

    port: int = 0
    hosts: list[str] = field(default_factory=list)


@pytest.fixture
async def origin() -> AsyncIterator[Origin]:
    seen = Origin()

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        head = await reader.readuntil(b"\r\n\r\n")
        for line in head.decode().split("\r\n"):
            if line.lower().startswith("host:"):
                seen.hosts.append(line.split(":", 1)[1].strip())
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    seen.port = server.sockets[0].getsockname()[1]
    async with server:
        yield seen


def fake_dns(monkeypatch: pytest.MonkeyPatch, *answers: Answer) -> list[str]:
    """Each call to the resolver pops the next answer (the last one repeats); returns the calls."""
    calls: list[str] = []
    queue = list(answers)

    async def resolve(host: str, port: int) -> Answer:
        calls.append(host)
        return queue.pop(0) if len(queue) > 1 else queue[0]

    monkeypatch.setattr(guard, "resolve_host", resolve)
    return calls


def client(policy: OutboundPolicy = DEFAULT_POLICY) -> httpx.AsyncClient:
    return guarded_client(policy, timeout=5.0)


async def test_connects_to_the_validated_address_and_keeps_the_host_header(
    origin: Origin, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = fake_dns(monkeypatch, ["127.0.0.1"])
    async with client() as c:
        response = await c.get(f"http://odoo.internal.test:{origin.port}/x")
    assert response.status_code == 200
    assert origin.hosts == [f"odoo.internal.test:{origin.port}"]
    assert calls == ["odoo.internal.test"]  # resolved exactly once per connection


async def test_link_local_literal_is_blocked_without_any_dns_or_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = fake_dns(monkeypatch, ["127.0.0.1"])
    async with client() as c:
        with pytest.raises(OutboundUrlBlocked):
            await c.get("http://169.254.169.254/latest/meta-data/")
    assert calls == []


async def test_a_name_resolving_to_link_local_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_dns(monkeypatch, ["169.254.169.254"])
    async with client() as c:
        with pytest.raises(OutboundUrlBlocked):
            await c.get("http://metadata.attacker.test/")


async def test_mixed_dns_answer_is_blocked_even_when_one_address_is_fine(
    origin: Origin, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_dns(monkeypatch, ["127.0.0.1", "169.254.169.254"])
    async with client() as c:
        with pytest.raises(OutboundUrlBlocked):
            await c.get(f"http://mixed.test:{origin.port}/")
    assert origin.hosts == []  # nothing was ever sent


async def test_rebinding_is_caught_because_every_new_connection_is_revalidated(
    origin: Origin, monkeypatch: pytest.MonkeyPatch
) -> None:
    # First answer is harmless, the second (after the "TTL expired") points at the metadata IP.
    fake_dns(monkeypatch, ["127.0.0.1"], ["169.254.169.254"])
    async with client() as c:
        assert (await c.get(f"http://rebind.test:{origin.port}/")).status_code == 200
        with pytest.raises(OutboundUrlBlocked):  # origin closed the connection: a new connect
            await c.get(f"http://rebind.test:{origin.port}/")
    assert len(origin.hosts) == 1


async def test_the_connection_uses_the_checked_answer_not_a_second_lookup(
    origin: Origin, monkeypatch: pytest.MonkeyPatch
) -> None:
    # If the connect stage resolved the name again it would get the second (blocked) answer.
    calls = fake_dns(monkeypatch, ["127.0.0.1"], ["169.254.169.254"])
    async with client() as c:
        response = await c.get(f"http://single.test:{origin.port}/")
    assert response.status_code == 200 and len(calls) == 1


async def test_strict_mode_blocks_loopback_unless_the_host_is_allowed(
    origin: Origin, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_dns(monkeypatch, ["127.0.0.1"])
    strict = OutboundPolicy(OutboundMode.STRICT)
    async with client(strict) as c:
        with pytest.raises(OutboundUrlBlocked):
            await c.get(f"http://odoo.test:{origin.port}/")
        with pytest.raises(OutboundUrlBlocked):
            await c.get(f"http://127.0.0.1:{origin.port}/")
    allowed = OutboundPolicy(OutboundMode.STRICT, frozenset({"odoo.test", "127.0.0.1"}))
    async with client(allowed) as c:
        assert (await c.get(f"http://odoo.test:{origin.port}/")).status_code == 200
        assert (await c.get(f"http://127.0.0.1:{origin.port}/")).status_code == 200


async def test_default_mode_still_allows_localhost(origin: Origin) -> None:
    async with client() as c:
        response = await c.get(f"http://127.0.0.1:{origin.port}/")
    assert response.status_code == 200


async def test_unresolvable_host_is_a_normal_connect_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(host: str, port: int) -> Answer:
        raise OSError("Name or service not known")

    monkeypatch.setattr(guard, "resolve_host", boom)
    async with client() as c:
        with pytest.raises(httpx.ConnectError):
            await c.get("http://nope.test/")


async def test_falls_back_to_the_next_validated_address_when_the_first_is_down(
    origin: Origin, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_dns(monkeypatch, ["127.0.0.2", "127.0.0.1"])  # 127.0.0.2 has no listener bound
    async with client() as c:
        assert (await c.get(f"http://multi.test:{origin.port}/")).status_code == 200


def test_env_proxies_are_not_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:3128")
    c = guarded_client(DEFAULT_POLICY, timeout=1.0)
    assert not c._mounts  # a proxy would resolve the target itself and bypass the policy


def test_guarded_transport_is_an_httpx_transport() -> None:
    assert isinstance(GuardedTransport(DEFAULT_POLICY), httpx.AsyncBaseTransport)


def test_blocking_connect_validates_every_address_before_connecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        guard, "resolve_host_blocking", lambda h, p: ["127.0.0.1", "169.254.169.254"]
    )
    with pytest.raises(OutboundUrlBlocked):
        guard.connect_guarded(DEFAULT_POLICY, "mixed.test", 80, 1.0)


def test_blocking_connect_connects_to_the_validated_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import socket

    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    monkeypatch.setattr(guard, "resolve_host_blocking", lambda h, p: ["127.0.0.1"])
    conn = guard.connect_guarded(DEFAULT_POLICY, "internal.test", server.getsockname()[1], 2.0)
    assert conn.getpeername() == server.getsockname()
    conn.close()
    server.close()


async def test_xmlrpc_transport_connects_through_the_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    from conector_odoo.infrastructure.odoo.xmlrpc import XmlRpcTransport

    monkeypatch.setattr(guard, "resolve_host_blocking", lambda h, p: ["169.254.169.254"])
    transport = XmlRpcTransport(
        "http://odoo.attacker.test", "db", "u", "k" * 20, max_retries=0, policy=DEFAULT_POLICY
    )
    with pytest.raises(OutboundUrlBlocked):
        await transport.authenticate()
