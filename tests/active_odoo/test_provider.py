"""``OdooConnectionProvider``: atomic swap, leases, close-after-in-flight."""

import asyncio
from typing import Any

import pytest

from conector_odoo.config import Settings
from conector_odoo.domain.active_odoo import OdooSource
from conector_odoo.domain.errors import OdooNotConfigured
from conector_odoo.infrastructure.odoo.provider import OdooConnection, OdooConnectionProvider


class FakeClient:
    def __init__(self, name: str) -> None:
        self.name = name
        self.closed = False
        self.close_calls = 0

    async def aclose(self) -> None:
        self.close_calls += 1
        self.closed = True


def connection(name: str, source: OdooSource = OdooSource.PROFILE) -> OdooConnection:
    return OdooConnection(
        FakeClient(name),  # type: ignore[arg-type]
        customers=object(),  # type: ignore[arg-type]
        products=object(),  # type: ignore[arg-type]
        orders=object(),  # type: ignore[arg-type]
        source=source,
        profile_id=1,
    )


def provider() -> OdooConnectionProvider:
    settings = Settings(_env_file=None, webhook_secret="whsec-test-secret-123")  # type: ignore[call-arg,arg-type]
    return OdooConnectionProvider(settings)


def fake(conn: OdooConnection) -> FakeClient:
    client: Any = conn.client
    assert isinstance(client, FakeClient)
    return client


def test_acquire_without_a_connection_raises_not_configured() -> None:
    p = provider()
    assert p.current is None
    assert p.try_acquire() is None
    with pytest.raises(OdooNotConfigured, match="admin"):
        p.acquire()


async def test_commit_makes_the_new_connection_current() -> None:
    p = provider()
    first = connection("a")
    await p.commit(first)
    lease = p.acquire()
    assert lease.connection is first
    lease.release()


async def test_old_client_is_closed_after_the_swap_when_idle() -> None:
    p = provider()
    old, new = connection("old"), connection("new")
    await p.commit(old)
    await p.commit(new)
    assert fake(old).closed
    assert not fake(new).closed


async def test_old_client_stays_open_until_its_in_flight_lease_is_released() -> None:
    p = provider()
    old, new = connection("old"), connection("new")
    await p.commit(old)
    lease = p.acquire()  # an in-flight request on the old connection
    await p.commit(new)
    assert not fake(old).closed  # still serving the request
    assert p.acquire().connection is new  # new requests already see the new one
    lease.release()
    await asyncio.sleep(0)  # let the scheduled close run
    await p.drain()
    assert fake(old).closed
    assert fake(old).close_calls == 1


async def test_release_is_idempotent() -> None:
    p = provider()
    old = connection("old")
    await p.commit(old)
    lease = p.acquire()
    await p.commit(connection("new"))
    lease.release()
    lease.release()
    await p.drain()
    assert fake(old).close_calls == 1


async def test_requests_during_a_swap_never_see_a_closed_client() -> None:
    p = provider()
    await p.commit(connection("c0"))
    seen_closed: list[str] = []
    stop = asyncio.Event()

    async def worker() -> int:
        served = 0
        while not stop.is_set():
            lease = p.acquire()
            try:
                await asyncio.sleep(0)  # yield mid-request so swaps interleave
                if fake(lease.connection).closed:
                    seen_closed.append(fake(lease.connection).name)
                await asyncio.sleep(0)
                if fake(lease.connection).closed:
                    seen_closed.append(fake(lease.connection).name)
                served += 1
            finally:
                lease.release()
        return served

    workers = [asyncio.create_task(worker()) for _ in range(8)]
    for i in range(1, 25):
        await p.commit(connection(f"c{i}"))
        await asyncio.sleep(0)
    stop.set()
    served = await asyncio.gather(*workers)
    await p.drain()
    assert seen_closed == []
    assert sum(served) > 24


async def test_disconnect_closes_the_current_and_leaves_none() -> None:
    p = provider()
    conn = connection("a")
    await p.commit(conn)
    await p.commit(None)
    assert p.current is None
    assert fake(conn).closed
    with pytest.raises(OdooNotConfigured):
        p.acquire()


async def test_discard_closes_a_prepared_connection_that_was_never_installed() -> None:
    p = provider()
    prepared = connection("never")
    await p.discard(prepared)
    assert fake(prepared).closed
    assert p.current is None


async def test_aclose_closes_current_and_retired_even_with_leases_outstanding() -> None:
    p = provider()
    old, new = connection("old"), connection("new")
    await p.commit(old)
    p.acquire()  # leaked lease: shutdown must still release the connection
    await p.commit(new)
    await p.aclose()
    assert fake(old).closed
    assert fake(new).closed
    assert p.current is None


async def test_a_failing_close_does_not_break_the_swap() -> None:
    p = provider()
    old = connection("old")

    async def boom() -> None:
        raise RuntimeError("close failed")

    fake(old).aclose = boom  # type: ignore[method-assign]
    await p.commit(old)
    new = connection("new")
    await p.commit(new)
    assert p.current is new
