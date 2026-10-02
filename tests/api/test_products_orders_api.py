import pytest

from tests.api.conftest import Env

ORDER = {
    "customer_id": 5,
    "company_id": 2,
    "lines": [
        {"product_id": 1, "quantity": 2, "price_unit": 9.5},
        {"product_id": 2, "quantity": 1},
    ],
}


def test_list_products_pages(env: Env) -> None:
    response = env.client.get("/products", params={"limit": 2, "offset": 1})
    assert response.status_code == 200
    assert [p["id"] for p in response.json()] == [2, 3]
    assert response.json()[0] == {
        "id": 2,
        "name": "P2",
        "default_code": None,
        "list_price": 0.0,
        "uom_name": None,
        "active": True,
    }


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 1001}, {"offset": -1}])
def test_list_products_validates_paging(env: Env, params: dict[str, int]) -> None:
    assert env.client.get("/products", params=params).status_code == 422


def test_get_product(env: Env) -> None:
    assert env.client.get("/products/3").json()["name"] == "P3"


def test_get_missing_product_is_404(env: Env) -> None:
    response = env.client.get("/products/99")
    assert response.status_code == 404
    assert response.json()["error"] == "not_found"


def test_create_sale_order_returns_201(env: Env) -> None:
    response = env.client.post("/sale-orders", json=ORDER)
    assert response.status_code == 201
    assert response.json() == {
        "id": 1,
        "customer_id": 5,
        "lines": [
            {"product_id": 1, "quantity": 2.0, "price_unit": 9.5},
            {"product_id": 2, "quantity": 1.0, "price_unit": None},
        ],
        "state": "draft",
        "name": "S00001",
        "amount_total": 0.0,
        "company_id": 2,
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"customer_id": 5, "lines": []},
        {"lines": ORDER["lines"]},
        {"customer_id": 0, "lines": ORDER["lines"]},
        {"customer_id": 5, "lines": [{"product_id": 1, "quantity": 0}]},
        {"customer_id": 5, "lines": [{"product_id": 0, "quantity": 1}]},
        {"customer_id": 5, "lines": [{"product_id": 1, "quantity": 1, "price_unit": -1}]},
        {"customer_id": 5, "lines": ORDER["lines"], "company_id": 0},
    ],
)
def test_create_sale_order_validates_the_body(env: Env, payload: dict[str, object]) -> None:
    response = env.client.post("/sale-orders", json=payload)
    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"
    assert env.orders.items == {}


def test_get_sale_order(env: Env) -> None:
    env.client.post("/sale-orders", json=ORDER)
    response = env.client.get("/sale-orders/1")
    assert response.status_code == 200
    assert response.json()["customer_id"] == 5


def test_get_missing_sale_order_is_404(env: Env) -> None:
    assert env.client.get("/sale-orders/9").status_code == 404


def test_confirm_sale_order(env: Env) -> None:
    env.client.post("/sale-orders", json=ORDER)
    response = env.client.post("/sale-orders/1/confirm")
    assert response.status_code == 200
    assert response.json()["state"] == "sale"


def test_confirm_is_idempotent_for_confirmed_orders(env: Env) -> None:
    env.client.post("/sale-orders", json=ORDER)
    env.client.post("/sale-orders/1/confirm")
    response = env.client.post("/sale-orders/1/confirm")
    assert response.status_code == 200
    assert env.orders.confirm_calls == 1


def test_confirm_missing_sale_order_is_404(env: Env) -> None:
    assert env.client.post("/sale-orders/9/confirm").status_code == 404
