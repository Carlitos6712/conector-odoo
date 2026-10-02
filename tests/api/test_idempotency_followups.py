"""T6 review follow-ups: uncertain outcomes, store failures, lifespan maintenance."""

import asyncio
import logging
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from conector_odoo.domain.entities import Customer, CustomerData
from conector_odoo.domain.errors import (
    OdooAuthError,
    OdooNotFound,
    OdooPermissionError,
    OdooUnavailable,
    OdooValidationError,
)
from conector_odoo.infrastructure.api.idempotency import IdempotencyGuard
from conector_odoo.infrastructure.idempotency.sqlite_store import SqliteIdempotencyStore
from conector_odoo.main import create_app
from tests.api.conftest import Env, make_settings

CUSTOMER = {"name": "Ada", "email": "ada@example.com"}
KEY = {"Idempotency-Key": "key-1"}
UNKNOWN_BODY = {
    "error": "idempotency_outcome_unknown",
    "detail": "previous attempt may have been applied; verify before retrying with a new key",
}


def test_odoo_unavailable_marks_the_key_unknown_and_retry_gets_409(env: Env) -> None:
    attempts = {"n": 0}

    async def down(data: CustomerData) -> Customer:
        attempts["n"] += 1
        raise OdooUnavailable("timeout after send")

    env.customers.create = down  # type: ignore[method-assign]
    first = env.client.post("/customers", json=CUSTOMER, headers=KEY)
    assert first.status_code == 502
    retry = env.client.post("/customers", json=CUSTOMER, headers=KEY)
    assert retry.status_code == 409
    assert retry.json() == UNKNOWN_BODY
    assert attempts["n"] == 1
    record = asyncio.run(env.app.state.container.idempotency.get("key-1", "POST /customers"))
    assert record is not None
    assert (record.status, record.response_status) == ("unknown", 502)
    assert record.response_body is not None
    assert "odoo_unavailable" in record.response_body


def test_unknown_key_with_another_body_is_still_422(env: Env) -> None:
    async def down(data: CustomerData) -> Customer:
        raise OdooUnavailable("boom")

    env.customers.create = down  # type: ignore[method-assign]
    env.client.post("/customers", json=CUSTOMER, headers=KEY)
    other = env.client.post("/customers", json={"name": "Grace"}, headers=KEY)
    assert other.status_code == 422
    assert other.json()["error"] == "idempotency_key_reused"


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (OdooValidationError("bad"), 422),
        (OdooNotFound("missing"), 404),
        (OdooAuthError("auth"), 401),
        (OdooPermissionError("denied"), 403),
    ],
)
def test_errors_that_guarantee_no_write_release_the_key(
    env: Env, error: Exception, status: int
) -> None:
    original = env.customers.create
    attempts = {"n": 0}

    async def flaky(data: CustomerData) -> Customer:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise error
        return await original(data)

    env.customers.create = flaky  # type: ignore[method-assign]
    assert env.client.post("/customers", json=CUSTOMER, headers=KEY).status_code == status
    assert env.client.post("/customers", json=CUSTOMER, headers=KEY).status_code == 201


def test_unexpected_exceptions_also_mark_the_key_unknown() -> None:
    app = create_app(make_settings())
    from conector_odoo.infrastructure.api.dependencies import get_customer_repository

    class Broken:
        async def create(self, data: CustomerData) -> Customer:
            raise RuntimeError("bug")

    app.dependency_overrides[get_customer_repository] = lambda: Broken()
    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.post("/customers", json=CUSTOMER, headers=KEY).status_code == 500
        retry = client.post("/customers", json=CUSTOMER, headers=KEY)
    assert retry.status_code == 409
    assert retry.json() == UNKNOWN_BODY


def test_stale_in_progress_key_is_reported_as_unknown_not_rerun(tmp_path: Path) -> None:
    db = tmp_path / "i.sqlite3"
    app = create_app(
        make_settings(idempotency_db_path=str(db), idempotency_in_progress_timeout_seconds=1)
    )
    from conector_odoo.infrastructure.api.dependencies import get_customer_repository
    from tests.unit.fakes import FakeCustomerRepository

    customers = FakeCustomerRepository()
    app.dependency_overrides[get_customer_repository] = lambda: customers
    with TestClient(app) as client:
        first = client.post("/customers", json=CUSTOMER, headers={"Idempotency-Key": "a"})
        assert first.status_code == 201
        # abandoned claim: a crashed worker left an in_progress row behind
        conn = sqlite3.connect(db)
        old = (datetime.now(UTC) - timedelta(seconds=5)).isoformat()
        conn.execute(
            "INSERT INTO idempotency_keys (key, scope, request_hash, status, created_at) "
            "VALUES ('b', 'POST /customers', 'x', 'in_progress', ?)",
            (old,),
        )
        conn.commit()
        conn.close()
        from fastapi import Request

        from conector_odoo.infrastructure.api.idempotency import request_hash
        from conector_odoo.infrastructure.api.schemas import CustomerCreate

        digest = request_hash(
            Request({"type": "http", "path_params": {}, "query_string": b"", "headers": []}),
            CustomerCreate(**CUSTOMER),
        )
        conn = sqlite3.connect(db)
        conn.execute("UPDATE idempotency_keys SET request_hash = ? WHERE key = 'b'", (digest,))
        conn.commit()
        conn.close()
        retry = client.post("/customers", json=CUSTOMER, headers={"Idempotency-Key": "b"})
    assert retry.status_code == 409
    assert retry.json() == UNKNOWN_BODY
    assert customers.calls.count("create") == 1


def test_complete_failure_is_logged_and_the_original_response_is_returned(
    env: Env, caplog: pytest.LogCaptureFixture
) -> None:
    store = env.app.state.container.idempotency

    async def broken(*args: object, **kwargs: object) -> None:
        raise sqlite3.OperationalError("disk full")

    store.complete = broken
    with caplog.at_level(logging.ERROR):
        response = env.client.post("/customers", json=CUSTOMER, headers=KEY)
    assert response.status_code == 201
    assert any("could not store" in r.getMessage() for r in caplog.records)


def test_begin_failure_is_a_503_not_a_raw_500(env: Env) -> None:
    store = env.app.state.container.idempotency

    async def broken(*args: object, **kwargs: object) -> None:
        raise sqlite3.OperationalError("database is locked")

    store.begin = broken
    response = env.client.post("/customers", json=CUSTOMER, headers=KEY)
    assert response.status_code == 503
    assert response.json()["error"] == "idempotency_store_unavailable"
    assert env.customers.calls == []


async def test_cancellation_keeps_the_key_claimed() -> None:
    store = SqliteIdempotencyStore(":memory:")
    started = asyncio.Event()

    fake_request = SimpleNamespace(
        method="POST",
        url=SimpleNamespace(path="/customers"),
        path_params={},
        query_params=SimpleNamespace(multi_items=lambda: []),
    )

    guard = IdempotencyGuard(fake_request, store, "k")  # type: ignore[arg-type]

    async def hang() -> object:
        started.set()
        await asyncio.sleep(60)
        raise AssertionError("unreachable")

    task = asyncio.create_task(guard.run(None, hang, 201))  # type: ignore[arg-type]
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    record = await store.get("k", "POST /customers")
    assert record is not None
    assert record.status == "in_progress"


def test_expired_rows_are_purged_at_startup(tmp_path: Path) -> None:
    db = tmp_path / "i.sqlite3"
    seed = SqliteIdempotencyStore(str(db))
    asyncio.run(seed.begin("old", "POST /customers", "h"))
    asyncio.run(seed.close())
    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE idempotency_keys SET created_at = ?",
        ((datetime.now(UTC) - timedelta(hours=48)).isoformat(),),
    )
    conn.commit()
    conn.close()
    app = create_app(make_settings(idempotency_db_path=str(db), idempotency_ttl_hours=24))
    with TestClient(app) as client:
        store = client.app.state.container.idempotency  # type: ignore[attr-defined]
        deadline = time.monotonic() + 3
        record = asyncio.run(store.get("old", "POST /customers"))
        while record is not None and time.monotonic() < deadline:
            time.sleep(0.05)
            record = asyncio.run(store.get("old", "POST /customers"))
    assert record is None


def test_purge_task_is_cancelled_on_shutdown() -> None:
    app = create_app(make_settings())
    with TestClient(app):
        task = app.state.purge_task
        assert not task.done()
    assert task.cancelled()


def test_store_is_closed_even_if_the_odoo_client_close_raises() -> None:
    app = create_app(make_settings())
    with pytest.raises(RuntimeError, match="close boom"), TestClient(app):
        container = app.state.container

        async def boom() -> None:
            raise RuntimeError("close boom")

        container.odoo_client.aclose = boom
        store = container.idempotency
    with pytest.raises(Exception, match="closed"):
        asyncio.run(store.get("k", "s"))
