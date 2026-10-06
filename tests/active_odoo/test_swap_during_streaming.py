"""A runtime switch must not close the client of an export that is still streaming."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from conector_odoo.domain.active_odoo import OdooSource
from conector_odoo.domain.entities import Customer, CustomerFilter
from conector_odoo.infrastructure.odoo.provider import OdooConnection
from conector_odoo.main import create_app
from tests.api.conftest import make_settings


class FakeClient:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class SlowCustomers:
    def __init__(self, gate: asyncio.Event) -> None:
        self.gate = gate

    async def iter_batches(
        self, filters: CustomerFilter, batch_size: int | None = None
    ) -> AsyncIterator[list[Customer]]:
        yield [Customer(id=1, name="Ada")]
        await self.gate.wait()  # the swap happens while the stream is open
        yield [Customer(id=2, name="Grace")]


def connection(customers: Any) -> OdooConnection:
    return OdooConnection(
        FakeClient(),  # type: ignore[arg-type]
        customers=customers,
        products=object(),  # type: ignore[arg-type]
        orders=object(),  # type: ignore[arg-type]
        source=OdooSource.PROFILE,
        profile_id=1,
    )


async def test_the_old_client_is_closed_only_after_the_stream_ends() -> None:
    app = create_app(make_settings(odoo_url=None, odoo_db=None, odoo_user=None, odoo_api_key=None))
    gate = asyncio.Event()
    async with app.router.lifespan_context(app):
        provider = app.state.container.odoo
        old = connection(SlowCustomers(gate))
        await provider.commit(old)
        # Raw ASGI: httpx's ASGITransport buffers the whole body, which would hide the stream.
        sent: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        disconnect = asyncio.Event()

        async def receive() -> dict[str, Any]:
            if not disconnect.is_set():
                disconnect.set()
                return {"type": "http.request", "body": b"", "more_body": False}
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        async def send(message: dict[str, Any]) -> None:
            await sent.put(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "path": "/customers/export",
            "raw_path": b"/customers/export",
            "query_string": b"",
            "headers": [],
            "server": ("test", 80),
            "client": ("127.0.0.1", 1),
            "scheme": "http",
            "root_path": "",
        }
        request = asyncio.create_task(app(scope, receive, send))  # type: ignore[arg-type]
        body = b""
        while b"Ada" not in body:
            message = await asyncio.wait_for(sent.get(), 5)
            if message["type"] == "http.response.start":
                assert message["status"] == 200
            body += message.get("body", b"")
        await provider.commit(connection(object()))  # switch mid-stream
        assert not old.client.closed  # type: ignore[attr-defined]
        gate.set()
        await asyncio.wait_for(request, 5)
        while not sent.empty():
            body += sent.get_nowait().get("body", b"")
        assert b"Grace" in body
        await provider.drain()
        assert old.client.closed  # type: ignore[attr-defined]
