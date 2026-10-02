import asyncio
from pathlib import Path

import httpx
import pytest
from fastapi import Request

from conector_odoo.domain.entities import Customer, CustomerData
from conector_odoo.domain.errors import CreatedButUnreadable
from conector_odoo.infrastructure.api.idempotency import request_hash
from conector_odoo.infrastructure.api.schemas import CustomerCreate
from conector_odoo.main import create_app
from tests.api.conftest import Env, build_env, make_settings

CUSTOMER = {"name": "Ada", "email": "ada@example.com"}
ORDER = {"customer_id": 5, "lines": [{"product_id": 1, "quantity": 2}]}
KEY = {"Idempotency-Key": "key-1"}


def test_duplicate_post_with_same_key_creates_once_and_replays(env: Env) -> None:
    first = env.client.post("/customers", json=CUSTOMER, headers=KEY)
    second = env.client.post("/customers", json=CUSTOMER, headers=KEY)
    assert first.status_code == second.status_code == 201
    assert second.json() == first.json()
    assert env.customers.calls.count("create") == 1
    assert "idempotent-replayed" not in first.headers
    assert second.headers["idempotent-replayed"] == "true"


def test_same_key_with_a_different_body_is_422(env: Env) -> None:
    env.client.post("/customers", json=CUSTOMER, headers=KEY)
    response = env.client.post("/customers", json={"name": "Grace"}, headers=KEY)
    assert response.status_code == 422
    assert response.json()["error"] == "idempotency_key_reused"
    assert env.customers.calls.count("create") == 1


def test_requests_without_a_key_behave_as_before(env: Env) -> None:
    env.client.post("/customers", json=CUSTOMER)
    env.client.post("/customers", json=CUSTOMER)
    assert env.customers.calls.count("create") == 2


def test_key_is_scoped_per_endpoint(env: Env) -> None:
    assert env.client.post("/customers", json=CUSTOMER, headers=KEY).status_code == 201
    assert env.client.post("/sale-orders", json=ORDER, headers=KEY).status_code == 201


def test_a_key_longer_than_255_characters_is_422(env: Env) -> None:
    response = env.client.post("/customers", json=CUSTOMER, headers={"Idempotency-Key": "k" * 256})
    assert response.status_code == 422
    assert env.customers.calls == []
    ok = env.client.post("/customers", json=CUSTOMER, headers={"Idempotency-Key": "k" * 255})
    assert ok.status_code == 201


def test_validation_failures_do_not_consume_the_key(env: Env) -> None:
    assert env.client.post("/customers", json={"name": ""}, headers=KEY).status_code == 422
    assert env.client.post("/customers", json=CUSTOMER, headers=KEY).status_code == 201


def test_created_but_unreadable_is_stored_and_replayed(env: Env) -> None:
    calls = {"n": 0}

    async def create(data: CustomerData) -> Customer:
        calls["n"] += 1
        raise CreatedButUnreadable("res.partner", 7, "customer 7 was created but unreadable")

    env.customers.create = create  # type: ignore[method-assign]
    first = env.client.post("/customers", json=CUSTOMER, headers=KEY)
    second = env.client.post("/customers", json=CUSTOMER, headers=KEY)
    assert first.status_code == second.status_code == 202
    assert second.json() == first.json()
    assert second.headers["location"] == "/customers/7"
    assert second.headers["idempotent-replayed"] == "true"
    assert calls["n"] == 1


def test_key_in_progress_is_409(env: Env) -> None:
    store = env.app.state.container.idempotency
    scope = {"type": "http", "path_params": {}, "query_string": b"", "headers": []}
    digest = request_hash(Request(scope), CustomerCreate(**CUSTOMER))
    assert asyncio.run(store.begin("key-1", "POST /customers", digest)) is None
    response = env.client.post("/customers", json=CUSTOMER, headers=KEY)
    assert response.status_code == 409
    assert response.json()["error"] == "idempotency_in_progress"
    assert env.customers.calls == []


def test_sale_order_create_and_confirm_are_idempotent(env: Env) -> None:
    created = env.client.post("/sale-orders", json=ORDER, headers={"Idempotency-Key": "o1"})
    again = env.client.post("/sale-orders", json=ORDER, headers={"Idempotency-Key": "o1"})
    assert again.json() == created.json()
    assert len(env.orders.items) == 1
    first = env.client.post("/sale-orders/1/confirm", headers={"Idempotency-Key": "c1"})
    second = env.client.post("/sale-orders/1/confirm", headers={"Idempotency-Key": "c1"})
    assert first.status_code == second.status_code == 200
    assert second.headers["idempotent-replayed"] == "true"
    assert env.orders.confirm_calls == 1


def test_the_same_key_on_another_order_confirm_is_a_different_request(env: Env) -> None:
    env.client.post("/sale-orders", json=ORDER)
    env.client.post("/sale-orders", json=ORDER)
    env.client.post("/sale-orders/1/confirm", headers=KEY)
    response = env.client.post("/sale-orders/2/confirm", headers=KEY)
    assert response.status_code == 200
    assert "idempotent-replayed" not in response.headers
    assert env.orders.confirm_calls == 2


def test_api_key_protection_still_applies_with_an_idempotency_key(secured_env: Env) -> None:
    response = secured_env.client.post("/customers", json=CUSTOMER, headers=KEY)
    assert response.status_code == 401


def test_the_store_is_closed_on_shutdown(tmp_path: Path) -> None:
    gen = build_env(make_settings(idempotency_db_path=str(tmp_path / "i.sqlite3")))
    env = next(gen)
    store = env.app.state.container.idempotency
    with pytest.raises(StopIteration):
        next(gen)
    with pytest.raises(Exception, match="closed"):
        asyncio.run(store.get("k", "s"))


async def test_two_concurrent_first_requests_one_wins_the_other_gets_409(
    tmp_path: Path,
) -> None:
    app = create_app(make_settings(idempotency_db_path=str(tmp_path / "i.sqlite3")))
    started = asyncio.Event()
    release = asyncio.Event()
    created: list[str] = []

    class SlowCustomers:
        async def create(self, data: CustomerData) -> Customer:
            created.append(data.name)
            started.set()
            await release.wait()
            return Customer(id=1, name=data.name)

    from conector_odoo.infrastructure.api.dependencies import get_customer_repository

    app.dependency_overrides[get_customer_repository] = lambda: SlowCustomers()
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        first: asyncio.Task[httpx.Response] = asyncio.create_task(
            client.post("/customers", json=CUSTOMER, headers=KEY)
        )
        await started.wait()
        second = await client.post("/customers", json=CUSTOMER, headers=KEY)
        release.set()
        winner = await first
    assert winner.status_code == 201
    assert second.status_code == 409
    assert created == ["Ada"]
