from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from conector_odoo.config import Settings
from conector_odoo.domain.entities import Product
from conector_odoo.infrastructure.api.dependencies import (
    get_customer_repository,
    get_odoo_client,
    get_product_repository,
    get_sale_order_repository,
)
from conector_odoo.main import create_app
from tests.unit.fakes import FakeCustomerRepository, FakeProductRepository, FakeSaleOrderRepository

API_KEY = "connector-secret-key"
ODOO_KEY = "odoo-secret-key"


class FakeOdooClient:
    def __init__(self) -> None:
        self.result: dict[str, Any] | BaseException = {"status": "ok", "uid": 42}

    async def check(self) -> dict[str, Any]:
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "odoo_url": "https://odoo.test",
        "odoo_db": "db",
        "odoo_user": "bot",
        "odoo_api_key": ODOO_KEY,
        "webhook_secret": "whsec",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


class Env:
    def __init__(self, app: FastAPI, client: TestClient) -> None:
        self.app = app
        self.client = client
        self.customers = FakeCustomerRepository()
        self.products = FakeProductRepository([Product(id=i, name=f"P{i}") for i in range(1, 4)])
        self.orders = FakeSaleOrderRepository()
        self.odoo = FakeOdooClient()
        overrides = app.dependency_overrides
        overrides[get_customer_repository] = lambda: self.customers
        overrides[get_product_repository] = lambda: self.products
        overrides[get_sale_order_repository] = lambda: self.orders
        overrides[get_odoo_client] = lambda: self.odoo


def build_env(settings: Settings) -> Iterator[Env]:
    app = create_app(settings)
    with TestClient(app) as client:
        yield Env(app, client)


@pytest.fixture
def env() -> Iterator[Env]:
    yield from build_env(make_settings())


@pytest.fixture
def secured_env() -> Iterator[Env]:
    yield from build_env(make_settings(connector_api_key=API_KEY))
