import http.client
import xmlrpc.client
from typing import Any
from xml.parsers.expat import ExpatError

import pytest

from conector_odoo.domain.errors import (
    OdooAuthError,
    OdooNotFound,
    OdooUnavailable,
)
from conector_odoo.infrastructure.odoo import xmlrpc as xmlrpc_module
from conector_odoo.infrastructure.odoo.xmlrpc import XmlRpcTransport

URL = "https://odoo.test"
KEY = "key-123"


class Registry:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, tuple[Any, ...]]] = []
        self.responses: list[Any] = []

    def pop(self) -> Any:
        item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class FakeProxy:
    def __init__(self, url: str, registry: Registry) -> None:
        self.url = url
        self.registry = registry

    def __getattr__(self, name: str) -> Any:
        def call(*args: Any) -> Any:
            self.registry.calls.append((self.url, name, args))
            return self.registry.pop()

        return call


@pytest.fixture
def registry(monkeypatch: pytest.MonkeyPatch) -> Registry:
    reg = Registry()
    monkeypatch.setattr(xmlrpc_module, "ServerProxy", lambda url, **kwargs: FakeProxy(url, reg))
    return reg


@pytest.fixture
def sleeps() -> list[float]:
    return []


@pytest.fixture
def transport(sleeps: list[float], registry: Registry) -> XmlRpcTransport:
    async def sleep(delay: float) -> None:
        sleeps.append(delay)

    return XmlRpcTransport(
        url=URL, db="db", user="bot", api_key=KEY, timeout=3.0, max_retries=2, sleep=sleep
    )


async def test_authenticate_calls_common_endpoint(
    transport: XmlRpcTransport, registry: Registry
) -> None:
    registry.responses = [7]
    assert await transport.authenticate() == 7
    assert registry.calls == [(f"{URL}/xmlrpc/2/common", "authenticate", ("db", "bot", KEY, {}))]


async def test_authenticate_false_is_auth_error(
    transport: XmlRpcTransport, registry: Registry
) -> None:
    registry.responses = [False]
    with pytest.raises(OdooAuthError) as info:
        await transport.authenticate()
    assert KEY not in str(info.value)


async def test_execute_kw_uses_object_endpoint(
    transport: XmlRpcTransport, registry: Registry
) -> None:
    registry.responses = [7, [{"id": 1}]]
    result = await transport.execute_kw("res.partner", "search_read", [[]], {"limit": 1})
    assert result == [{"id": 1}]
    assert registry.calls[1] == (
        f"{URL}/xmlrpc/2/object",
        "execute_kw",
        ("db", 7, KEY, "res.partner", "search_read", [[]], {"limit": 1}),
    )


async def test_faults_are_mapped(transport: XmlRpcTransport, registry: Registry) -> None:
    registry.responses = [7, xmlrpc.client.Fault(2, "Record does not exist or has been deleted.")]
    with pytest.raises(OdooNotFound):
        await transport.execute_kw("res.partner", "read", [[1]])
    registry.responses = [xmlrpc.client.Fault(3, "Access Denied")]
    with pytest.raises(OdooAuthError):
        await transport.authenticate()


async def test_protocol_error_is_unavailable(
    transport: XmlRpcTransport, registry: Registry
) -> None:
    registry.responses = [7, xmlrpc.client.ProtocolError(URL, 502, "Bad Gateway", {})]
    with pytest.raises(OdooUnavailable):
        await transport.execute_kw("res.partner", "search", [[]])


async def test_os_errors_retry_idempotent_calls(
    transport: XmlRpcTransport, registry: Registry, sleeps: list[float]
) -> None:
    registry.responses = [7, ConnectionRefusedError("x"), TimeoutError("t"), [1]]
    assert await transport.execute_kw("res.partner", "search", [[]]) == [1]
    assert sleeps == [0.5, 1.0]


async def test_os_errors_never_retry_create(
    transport: XmlRpcTransport, registry: Registry, sleeps: list[float]
) -> None:
    registry.responses = [7, ConnectionResetError("x")]
    with pytest.raises(OdooUnavailable):
        await transport.execute_kw("res.partner", "create", [[{"name": "A"}]])
    assert len(registry.calls) == 2
    assert sleeps == []


@pytest.mark.parametrize(
    "error",
    [
        http.client.IncompleteRead(b"partial"),
        http.client.BadStatusLine("garbage"),
        ExpatError("not well-formed"),
    ],
)
async def test_http_and_parser_errors_are_unavailable(
    transport: XmlRpcTransport, registry: Registry, error: Exception
) -> None:
    registry.responses = [7, error]
    with pytest.raises(OdooUnavailable) as info:
        await transport.execute_kw("res.partner", "create", [[{"name": "A"}]])
    assert KEY not in str(info.value)
