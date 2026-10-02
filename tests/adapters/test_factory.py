from typing import Any

import pytest

from conector_odoo.config import Settings
from conector_odoo.infrastructure.odoo.client import OdooClient
from conector_odoo.infrastructure.odoo.factory import build_odoo_client, build_transport
from conector_odoo.infrastructure.odoo.json2 import Json2Transport
from conector_odoo.infrastructure.odoo.jsonrpc import JsonRpcTransport
from conector_odoo.infrastructure.odoo.xmlrpc import XmlRpcTransport


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "odoo_url": "https://odoo.test",
        "odoo_db": "db",
        "odoo_user": "bot",
        "odoo_api_key": "secret-key",
        "webhook_secret": "w",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


@pytest.mark.parametrize(
    ("protocol", "expected"),
    [("jsonrpc", JsonRpcTransport), ("xmlrpc", XmlRpcTransport), ("json2", Json2Transport)],
)
def test_build_transport_selects_by_protocol(protocol: str, expected: type) -> None:
    transport = build_transport(make_settings(odoo_protocol=protocol))
    assert type(transport) is expected


def test_build_transport_passes_secret_and_tuning() -> None:
    transport = build_transport(make_settings(odoo_timeout_seconds=7.5, odoo_max_retries=4))
    assert transport._api_key == "secret-key"  # type: ignore[attr-defined]
    assert transport._timeout == 7.5  # type: ignore[attr-defined]
    assert transport._max_retries == 4  # type: ignore[attr-defined]


def test_build_odoo_client_uses_company_id() -> None:
    client = build_odoo_client(make_settings(odoo_protocol="json2", odoo_company_id=3))
    assert isinstance(client, OdooClient)
    assert client._company_id == 3
    assert isinstance(client._transport, Json2Transport)


def test_build_odoo_client_without_company() -> None:
    assert build_odoo_client(make_settings())._company_id is None
