"""T5 review follow-ups: read-back errors, error logging, scrubbing, startup warning."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from conector_odoo.application.pagination import MAX_PAGE_SIZE
from conector_odoo.domain.entities import CustomerData, SaleOrderData
from conector_odoo.domain.errors import CreatedButUnreadable, OdooUnavailable
from conector_odoo.infrastructure.api.errors import scrub
from conector_odoo.infrastructure.api.routers import customers as customers_router
from conector_odoo.infrastructure.api.routers import products as products_router
from conector_odoo.main import create_app
from tests.api.conftest import API_KEY, ODOO_KEY, Env, make_settings

ORDER = {"customer_id": 5, "lines": [{"product_id": 1, "quantity": 2}]}


def test_created_but_unreadable_customer_is_202_with_id_and_location(env: Env) -> None:
    async def create(data: CustomerData) -> None:
        raise CreatedButUnreadable("res.partner", 7, "customer 7 was created but unreadable")

    env.customers.create = create  # type: ignore[method-assign]
    response = env.client.post("/customers", json={"name": "Ada"})
    assert response.status_code == 202
    assert response.headers["location"] == "/customers/7"
    assert response.json() == {
        "error": "created_but_unreadable",
        "detail": "customer 7 was created but unreadable",
        "id": 7,
        "model": "res.partner",
    }


def test_created_but_unreadable_sale_order_is_202_with_location(env: Env) -> None:
    async def create(data: SaleOrderData) -> None:
        raise CreatedButUnreadable("sale.order", 9, "sale order 9 was created but unreadable")

    env.orders.create = create  # type: ignore[method-assign]
    response = env.client.post("/sale-orders", json=ORDER)
    assert response.status_code == 202
    assert response.headers["location"] == "/sale-orders/9"
    assert response.json()["id"] == 9


def test_created_but_unreadable_detail_is_scrubbed(secured_env: Env) -> None:
    async def create(data: CustomerData) -> None:
        raise CreatedButUnreadable("res.partner", 7, f"failed with {API_KEY}")

    secured_env.customers.create = create  # type: ignore[method-assign]
    response = secured_env.client.post(
        "/customers", json={"name": "Ada"}, headers={"X-API-Key": API_KEY}
    )
    assert response.status_code == 202
    assert API_KEY not in response.text


def test_failed_request_log_carries_scrubbed_message_and_request_id(
    secured_env: Env, caplog: pytest.LogCaptureFixture
) -> None:
    async def failing(customer_id: int) -> None:
        raise OdooUnavailable(f"upstream said {API_KEY} and {ODOO_KEY}")

    secured_env.customers.get = failing  # type: ignore[method-assign]
    with caplog.at_level(logging.WARNING):
        secured_env.client.get(
            "/customers/1", headers={"X-API-Key": API_KEY, "X-Request-ID": "req-42"}
        )
    record = next(r for r in caplog.records if r.getMessage() == "request failed")
    assert record.request_id == "req-42"  # type: ignore[attr-defined]
    assert "upstream said" in record.detail  # type: ignore[attr-defined]
    assert API_KEY not in caplog.text
    assert ODOO_KEY not in caplog.text


def test_connector_api_key_is_scrubbed_from_error_details(secured_env: Env) -> None:
    async def failing(customer_id: int) -> None:
        raise OdooUnavailable(f"upstream echoed {API_KEY}")

    secured_env.customers.get = failing  # type: ignore[method-assign]
    response = secured_env.client.get("/customers/1", headers={"X-API-Key": API_KEY})
    assert response.status_code == 502
    assert API_KEY not in response.text
    assert "***" in response.json()["detail"]


def test_scrub_ignores_secrets_shorter_than_eight_characters() -> None:
    settings = make_settings(odoo_api_key="abc")
    assert scrub("abcdef", settings) == "abcdef"


def test_routers_use_the_application_page_size_limit() -> None:
    assert customers_router.MAX_PAGE_SIZE == MAX_PAGE_SIZE
    assert products_router.MAX_PAGE_SIZE == MAX_PAGE_SIZE


@contextmanager
def capture(name: str) -> Iterator[list[logging.LogRecord]]:
    records: list[logging.LogRecord] = []

    class Collect(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = Collect(logging.WARNING)
    logger = logging.getLogger(name)
    logger.addHandler(handler)
    try:
        yield records
    finally:
        logger.removeHandler(handler)


def test_startup_warns_when_the_connector_api_key_is_not_configured() -> None:
    with capture("conector_odoo.main") as records, TestClient(create_app(make_settings())):
        pass
    assert any("unauthenticated" in r.getMessage() for r in records)


def test_startup_does_not_warn_when_the_connector_api_key_is_configured() -> None:
    settings = make_settings(connector_api_key=API_KEY)
    with capture("conector_odoo.main") as records, TestClient(create_app(settings)):
        pass
    assert not any("unauthenticated" in r.getMessage() for r in records)
