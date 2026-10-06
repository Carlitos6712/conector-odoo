import pytest

from conector_odoo.domain.entities import CustomerData
from tests.api.conftest import Env


def new_customer(env: Env, **overrides: object) -> int:
    data = {"name": "Ada", "email": "ada@x.io", **overrides}
    response = env.client.post("/customers", json=data)
    assert response.status_code == 201
    return int(response.json()["id"])


def test_create_customer_returns_201_and_the_customer(env: Env) -> None:
    response = env.client.post(
        "/customers",
        json={"name": "Ada", "email": "ada@x.io", "country_code": "ES", "is_company": True},
    )
    assert response.status_code == 201
    assert response.json() == {
        "id": 1,
        "name": "Ada",
        "email": "ada@x.io",
        "phone": None,
        "street": None,
        "city": None,
        "zip": None,
        "country_code": "ES",
        "vat": None,
        "is_company": True,
        "active": True,
    }


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"name": ""},
        {"name": "Ada", "email": "not-an-email"},
        {"name": "Ada", "country_code": "ESP"},
        {"name": "Ada", "unknown": 1},
    ],
)
def test_create_customer_validates_the_body(env: Env, payload: dict[str, object]) -> None:
    response = env.client.post("/customers", json=payload)
    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "validation_error"
    assert isinstance(body["detail"], str)
    assert env.customers.calls == []


def test_get_customer(env: Env) -> None:
    customer_id = new_customer(env)
    response = env.client.get(f"/customers/{customer_id}")
    assert response.status_code == 200
    assert response.json()["name"] == "Ada"


def test_get_missing_customer_is_404_with_error_body(env: Env) -> None:
    response = env.client.get("/customers/99")
    assert response.status_code == 404
    assert response.json() == {"error": "not_found", "detail": "customer 99 not found"}


def test_customer_id_must_be_positive(env: Env) -> None:
    assert env.client.get("/customers/0").status_code == 422


def test_patch_customer_updates_only_given_fields(env: Env) -> None:
    customer_id = new_customer(env, city="Paris")
    response = env.client.patch(f"/customers/{customer_id}", json={"phone": "123"})
    assert response.status_code == 200
    assert response.json()["phone"] == "123"
    assert response.json()["city"] == "Paris"


@pytest.mark.parametrize("payload", [{}, {"phone": None}, {"nope": 1}, {"email": "bad"}])
def test_patch_customer_rejects_empty_or_invalid_bodies(
    env: Env, payload: dict[str, object]
) -> None:
    customer_id = new_customer(env)
    response = env.client.patch(f"/customers/{customer_id}", json=payload)
    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"


def test_patch_missing_customer_is_404(env: Env) -> None:
    assert env.client.patch("/customers/99", json={"phone": "1"}).status_code == 404


def test_patch_blank_name_is_rejected_by_the_use_case(env: Env) -> None:
    customer_id = new_customer(env)
    response = env.client.patch(f"/customers/{customer_id}", json={"name": "  "})
    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"


async def test_search_customers_filters_and_pages(env: Env) -> None:
    for i in range(5):
        await env.customers.create(CustomerData(name=f"Ada {i}", email=f"a{i}@x.io"))
    await env.customers.create(CustomerData(name="Bob", email="bob@x.io"))
    by_email = env.client.get("/customers", params={"email": "bob@x.io"})
    assert [c["name"] for c in by_email.json()] == ["Bob"]
    by_name = env.client.get("/customers", params={"name": "ada", "limit": 2, "offset": 1})
    assert [c["name"] for c in by_name.json()] == ["Ada 1", "Ada 2"]


def test_search_customers_defaults(env: Env) -> None:
    response = env.client.get("/customers")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 1001}, {"offset": -1}])
def test_search_customers_validates_paging(env: Env, params: dict[str, int]) -> None:
    assert env.client.get("/customers", params=params).status_code == 422


def test_search_customers_accepts_the_max_page_size(env: Env) -> None:
    assert env.client.get("/customers", params={"limit": 1000}).status_code == 200
