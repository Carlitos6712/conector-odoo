"""The e2e fake Odoo must speak exactly the JSON-RPC subset the real adapter uses."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from conector_odoo.infrastructure.odoo.jsonrpc import JsonRpcTransport
from tests.e2e_support.fake_odoo import FakeOdooConfig, create_fake_odoo_app

DB, LOGIN, KEY = "e2e", "admin", "e2e-api-key-0123456789"


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_fake_odoo_app(FakeOdooConfig(db=DB, login=LOGIN, api_key=KEY)))


def rpc(client: TestClient, service: str, method: str, *args: Any) -> Any:
    body = {
        "jsonrpc": "2.0",
        "method": "call",
        "params": {"service": service, "method": method, "args": list(args)},
        "id": 1,
    }
    response = client.post("/jsonrpc", json=body)
    assert response.status_code == 200
    return response.json()


def call(client: TestClient, model: str, method: str, args: list[Any], **kwargs: Any) -> Any:
    reply = rpc(client, "object", "execute_kw", DB, 2, KEY, model, method, args, kwargs)
    assert "error" not in reply, reply
    return reply["result"]


def test_root_answers_for_the_connection_probe(client: TestClient) -> None:
    assert client.get("/").status_code == 200


def test_authenticate_accepts_the_configured_credentials(client: TestClient) -> None:
    assert rpc(client, "common", "authenticate", DB, LOGIN, KEY, {})["result"] == 2


@pytest.mark.parametrize(
    "creds", [(DB, LOGIN, "wrong"), (DB, "other", KEY), ("other-db", LOGIN, KEY)]
)
def test_authenticate_rejects_bad_credentials(client: TestClient, creds: tuple[str, ...]) -> None:
    assert rpc(client, "common", "authenticate", *creds, {})["result"] is False


def test_execute_kw_with_a_bad_key_is_an_odoo_style_error(client: TestClient) -> None:
    reply = rpc(
        client, "object", "execute_kw", DB, 2, "nope", "res.partner", "search_read", [[]], {}
    )
    assert reply["error"]["data"]["name"].endswith("AccessDenied")


def test_fields_get_describes_res_partner(client: TestClient) -> None:
    fields = call(
        client, "res.partner", "fields_get", [], attributes=["string", "type", "relation"]
    )
    assert fields["name"]["type"] == "char"
    assert fields["country_id"]["type"] == "many2one"
    assert fields["country_id"]["relation"] == "res.country"
    assert "id" in fields


def test_unknown_model_has_no_fields(client: TestClient) -> None:
    assert call(client, "x.unknown", "fields_get", [], attributes=["type"]) == {}


def test_create_then_read_and_search(client: TestClient) -> None:
    new_id = call(client, "res.partner", "create", [{"name": "Acme", "ref": "u-1"}])
    assert isinstance(new_id, int)
    [row] = call(client, "res.partner", "read", [[new_id]], fields=["name", "ref", "city"])
    assert row == {"id": new_id, "name": "Acme", "ref": "u-1", "city": False}
    found = call(
        client, "res.partner", "search_read", [[["ref", "=", "u-1"]]], fields=["name"], limit=1
    )
    assert [r["name"] for r in found] == ["Acme"]
    assert (
        call(client, "res.partner", "search_read", [[["ref", "=", "zzz"]]], fields=["name"]) == []
    )


def test_write_updates_and_reports_true(client: TestClient) -> None:
    new_id = call(client, "res.partner", "create", [{"name": "Acme"}])
    assert call(client, "res.partner", "write", [[new_id], {"city": "Madrid"}]) is True
    [row] = call(client, "res.partner", "read", [[new_id]], fields=["city"])
    assert row["city"] == "Madrid"


def test_keyset_pagination_and_order(client: TestClient) -> None:
    ids = [call(client, "res.partner", "create", [{"name": f"P{i}"}]) for i in range(5)]
    page = call(
        client,
        "res.partner",
        "search_read",
        [[["id", ">", ids[1]]]],
        fields=["name"],
        limit=2,
        order="id asc",
    )
    assert [r["id"] for r in page] == ids[2:4]


def test_required_name_is_enforced(client: TestClient) -> None:
    reply = rpc(
        client, "object", "execute_kw", DB, 2, KEY, "res.partner", "create", [{"city": "x"}], {}
    )
    assert "error" in reply
    assert "name" in reply["error"]["data"]["message"]


def test_unknown_field_is_rejected(client: TestClient) -> None:
    reply = rpc(
        client,
        "object",
        "execute_kw",
        DB,
        2,
        KEY,
        "res.partner",
        "create",
        [{"name": "A", "bogus": 1}],
        {},
    )
    assert "error" in reply


def test_model_discovery_lists_res_partner(client: TestClient) -> None:
    rows = call(
        client, "ir.model", "search_read", [[["transient", "=", False]]], fields=["model", "name"]
    )
    assert "res.partner" in {r["model"] for r in rows}


async def test_real_transport_round_trips_against_the_fake() -> None:
    """The production JsonRpcTransport (not a hand-built payload) works against the fake."""
    import httpx

    app = create_fake_odoo_app(FakeOdooConfig(db=DB, login=LOGIN, api_key=KEY))
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fake")
    transport = JsonRpcTransport("http://fake", DB, LOGIN, KEY, client=http, max_retries=0)
    assert await transport.authenticate() == 2
    new_id = await transport.execute_kw("res.partner", "create", [{"name": "Via transport"}])
    rows = await transport.execute_kw("res.partner", "read", [[new_id]], {"fields": ["name"]})
    assert rows == [{"id": new_id, "name": "Via transport"}]
    await http.aclose()
